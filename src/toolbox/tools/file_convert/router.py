"""HTTP routes for the file-convert tool.

URL prefix is set when the router is mounted in `toolbox.api`
(`/tools/file-convert`). Endpoints here use plain paths so they read clearly
against the prefix.
"""

import logging
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import BinaryIO

import anyio
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from ...core.engines_graph import ENGINES, build_graph
from ...core.errors import ToolboxError
from ...core.limits import RATE_LIMIT, limiter
from ...core import detect, llm_settings
from ...core.pipeline import convert

log = logging.getLogger("toolbox.file_convert")

router = APIRouter(tags=["file-convert"])

# Job files live in a private-per-process dir under the system temp dir.
# Mode 0700 + symlink refusal keep other local users from pre-planting a
# symlinked dir and redirecting our writes.
_OUTPUT_DIR = Path(tempfile.gettempdir()) / "toolbox_out"
if _OUTPUT_DIR.is_symlink():
    raise RuntimeError(f"{_OUTPUT_DIR} is a symlink; refusing to write")
_OUTPUT_DIR.mkdir(mode=0o700, exist_ok=True)

# In-memory job store for async conversion progress tracking.
# Entries are removed on download or by the TTL sweep — never on their own,
# so clients that submit but never download don't leak memory + disk.
_MAX_PENDING_JOBS = 32
_JOB_TTL_SECONDS = 3600
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_exec = ThreadPoolExecutor(max_workers=4, thread_name_prefix="toolbox-convert")


def startup_cleanup() -> None:
    """Wipe job files left by a previous process (crash, restart, no download)."""
    shutil.rmtree(_OUTPUT_DIR, ignore_errors=True)
    _OUTPUT_DIR.mkdir(mode=0o700, exist_ok=True)


def shutdown_executor() -> None:
    """Cancel queued conversions and release worker threads on app shutdown."""
    _exec.shutdown(wait=False, cancel_futures=True)


def _sweep_expired_jobs() -> None:
    """Drop jobs older than the TTL and delete their files. Runs on each submit."""
    cutoff = time.monotonic() - _JOB_TTL_SECONDS
    expired: list[str] = []
    with _jobs_lock:
        for job_id, job in list(_jobs.items()):
            if job["created_at"] < cutoff:
                expired.append(job_id)
                del _jobs[job_id]
    for job_id in expired:
        work_dir = _OUTPUT_DIR / job_id
        log.info("reaping expired job %s", job_id)
        shutil.rmtree(work_dir, ignore_errors=True)


def _sanitize_filename(raw: str | None) -> str:
    """Reduce a client-supplied filename to a bare name.

    `UploadFile.filename` comes straight from the request's Content-Disposition
    and can carry traversal (`../../x`, absolute paths). `Path(...).name`
    strips all directory components on both POSIX and Windows forms.
    """
    name = Path(raw or "").name
    if not name or name in {".", ".."} or "\x00" in name:
        raise HTTPException(400, "invalid filename")
    return name


_KNOWN_FORMATS = frozenset(detect.EXTENSION_MAP.values())


def _validate_target(to: str) -> str:
    """Whitelist the target format before it reaches the filesystem."""
    fmt = to.strip().lstrip(".").lower()
    if fmt not in _KNOWN_FORMATS:
        raise HTTPException(422, f"unsupported target format: {to!r}")
    return fmt


def _save_upload(src: BinaryIO, dst: Path) -> None:
    with dst.open("wb") as f:
        shutil.copyfileobj(src, f)


@router.get("/engines")
def list_engines():
    out = []
    for e in ENGINES:
        info = {"name": e.name, "available": e.available, "edges": e.edges()}
        if e.name == "vision-llm":
            try:
                pid, label, _base, model = e.active_config()  # type: ignore[attr-defined]
                info["active_provider"] = {"id": pid, "label": label, "model": model}
            except Exception:
                # Distinguish "configured but unreadable" from "not configured"
                # in the logs; clients just see active_provider: null.
                log.exception("failed to read active vision-llm config")
                info["active_provider"] = None
        out.append(info)
    return out


@router.get("/routes")
def list_routes():
    graph = build_graph()
    return {
        src: [{"to": dst, "engine": engines[0].name} for dst, engines in nbrs]
        for src, nbrs in graph.items()
    }


def _maybe_limit(fn):
    if not RATE_LIMIT:
        return fn
    return limiter.limit(RATE_LIMIT)(fn)


# ---------------------------------------------------------------------------
# Async job endpoints (submit → poll → download)
# ---------------------------------------------------------------------------

@router.post("/jobs")
@_maybe_limit
async def submit_job(
    request: Request,
    file: UploadFile = File(...),
    to: str = Query(..., description="Target format, e.g. 'md', 'pdf', 'docx'"),
    llm_provider: str = Form(""),
    llm_model: str = Form(""),
    llm_api_key: str = Form(""),
):
    """Submit a conversion job. Returns job_id immediately; use GET /jobs/{id} to poll.

    Optional form fields llm_provider / llm_model / llm_api_key activate the
    Vision-LLM engine for this job only. Credentials are used in-process and
    never persisted.
    """
    _sweep_expired_jobs()

    filename = _sanitize_filename(file.filename)
    dst_fmt = _validate_target(to)

    with _jobs_lock:
        pending = sum(1 for j in _jobs.values() if j["status"] == "processing")
    if pending >= _MAX_PENDING_JOBS:
        raise HTTPException(
            503, "server busy: too many conversions in flight, retry later"
        )

    job_id = uuid.uuid4().hex
    work_dir = _OUTPUT_DIR / job_id
    work_dir.mkdir(parents=True)

    src_path = work_dir / filename
    # Starlette already buffered the body into a SpooledTemporaryFile; copy it
    # to its final spot off the event loop so a slow disk can't stall /health
    # and every other concurrent request.
    await anyio.to_thread.run_sync(_save_upload, file.file, src_path)

    with _jobs_lock:
        _jobs[job_id] = {
            "status": "processing",
            "progress": 0,
            "work_dir": str(work_dir),
            "created_at": time.monotonic(),
        }

    src_path_str = str(src_path)
    user_llm = (
        {"provider": llm_provider, "model": llm_model, "api_key": llm_api_key}
        if llm_provider and llm_model and llm_api_key
        else None
    )

    def run() -> None:
        if user_llm:
            llm_settings.set_request_config(user_llm)
        src = Path(src_path_str)
        dst_name = f"{src.stem}.{dst_fmt}"
        dst = work_dir / dst_name
        try:
            def on_step(step: int, total: int) -> None:
                pct = int(step / total * 100)
                with _jobs_lock:
                    if job_id in _jobs:
                        _jobs[job_id]["progress"] = pct

            convert(src, dst, dst_fmt=dst_fmt, on_progress=on_step)

            with _jobs_lock:
                _jobs[job_id].update({
                    "status": "done",
                    "progress": 100,
                    "result": str(dst),
                    "filename": dst_name,
                })
        except ToolboxError as e:
            with _jobs_lock:
                if job_id in _jobs:
                    _jobs[job_id].update({
                        "status": "failed",
                        "error": f"{type(e).__name__}: {e}",
                    })
        except Exception as e:
            log.exception("job %s failed unexpectedly", job_id)
            with _jobs_lock:
                if job_id in _jobs:
                    _jobs[job_id].update({"status": "failed", "error": str(e)})
        finally:
            if user_llm:
                llm_settings.set_request_config(None)

    try:
        _exec.submit(run)
    except RuntimeError as e:
        # Executor already shut down (app closing): don't strand the job as
        # "processing" forever.
        with _jobs_lock:
            _jobs.pop(job_id, None)
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(503, "server is shutting down") from e

    # JSONResponse (not a bare dict): slowapi's header injection requires the
    # endpoint to return a Response instance, and a bare dict 500s every
    # successful submit when TOOLBOX_RATE_LIMIT is set.
    return JSONResponse({"job_id": job_id})


@router.get("/jobs/{job_id}")
def get_job_status(job_id: str):
    """Poll conversion progress. Returns {status, progress, error?, filename?}."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {
        "status": job["status"],
        "progress": job.get("progress", 0),
        "error": job.get("error"),
        "filename": job.get("filename"),
    }


@router.get("/jobs/{job_id}/result")
def get_job_result(job_id: str):
    """Download the converted file. Cleans up job files after serving."""
    with _jobs_lock:
        job = _jobs.get(job_id)

    if not job or job["status"] != "done":
        raise HTTPException(404, "job not ready or not found")

    result_path = job.get("result", "")
    filename = job.get("filename", "result")
    work_dir_str = job.get("work_dir", "")

    def cleanup() -> None:
        with _jobs_lock:
            _jobs.pop(job_id, None)
        if work_dir_str:
            shutil.rmtree(work_dir_str, ignore_errors=True)

    return FileResponse(
        result_path,
        filename=filename,
        media_type="application/octet-stream",
        background=BackgroundTask(cleanup),
    )


# ---------------------------------------------------------------------------
# Legacy synchronous endpoint (kept for CLI / backward compat)
# ---------------------------------------------------------------------------

@router.post(
    "/convert",
    deprecated=True,
    description="Legacy synchronous conversion; use POST /jobs instead.",
)
@_maybe_limit
def convert_endpoint(
    request: Request,
    file: UploadFile = File(...),
    to: str = Query(..., description="Target format, e.g. 'md', 'pdf', 'docx'"),
):
    if not file.filename:
        raise HTTPException(400, "filename required")

    filename = _sanitize_filename(file.filename)
    dst_fmt = _validate_target(to)

    job_id = uuid.uuid4().hex
    work_dir = _OUTPUT_DIR / job_id
    work_dir.mkdir(parents=True)

    src_path = work_dir / filename
    _save_upload(file.file, src_path)

    dst_name = f"{src_path.stem}.{dst_fmt}"
    dst_path = work_dir / dst_name
    try:
        convert(src_path, dst_path, dst_fmt=dst_fmt)
    except ToolboxError as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(e.status_code, str(e)) from e

    return FileResponse(
        dst_path,
        filename=dst_name,
        media_type="application/octet-stream",
    )
