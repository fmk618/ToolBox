"""HTTP routes for the file-convert tool.

URL prefix is set when the router is mounted in `toolbox.api`
(`/tools/file-convert`). Endpoints here use plain paths so they read clearly
against the prefix.
"""

import shutil
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from ...core.engines_graph import ENGINES, build_graph
from ...core.errors import ToolboxError
from ...core.limits import RATE_LIMIT, limiter
from ...core.pipeline import convert

router = APIRouter(tags=["file-convert"])

_OUTPUT_DIR = Path(tempfile.gettempdir()) / "toolbox_out"
_OUTPUT_DIR.mkdir(exist_ok=True)

# In-memory job store for async conversion progress tracking
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_exec = ThreadPoolExecutor(max_workers=4, thread_name_prefix="toolbox-convert")


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
):
    """Submit a conversion job. Returns job_id immediately; use GET /jobs/{id} to poll."""
    if not file.filename:
        raise HTTPException(400, "filename required")

    job_id = uuid.uuid4().hex[:12]
    work_dir = _OUTPUT_DIR / job_id
    work_dir.mkdir(parents=True, exist_ok=True)

    src_path = work_dir / file.filename
    with src_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    with _jobs_lock:
        _jobs[job_id] = {
            "status": "processing",
            "progress": 0,
            "work_dir": str(work_dir),
        }

    dst_fmt = to
    src_path_str = str(src_path)

    def run() -> None:
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
            with _jobs_lock:
                if job_id in _jobs:
                    _jobs[job_id].update({"status": "failed", "error": str(e)})

    _exec.submit(run)
    return {"job_id": job_id}


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

@router.post("/convert")
@_maybe_limit
def convert_endpoint(
    request: Request,
    file: UploadFile = File(...),
    to: str = Query(..., description="Target format, e.g. 'md', 'pdf', 'docx'"),
):
    if not file.filename:
        raise HTTPException(400, "filename required")

    job_id = uuid.uuid4().hex[:12]
    work_dir = _OUTPUT_DIR / job_id
    work_dir.mkdir(parents=True, exist_ok=True)

    src_path = work_dir / file.filename
    with src_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    dst_name = f"{src_path.stem}.{to}"
    dst_path = work_dir / dst_name
    try:
        convert(src_path, dst_path, dst_fmt=to)
    except ToolboxError as e:
        raise HTTPException(400, f"{type(e).__name__}: {e}")

    return FileResponse(
        dst_path,
        filename=dst_name,
        media_type="application/octet-stream",
    )
