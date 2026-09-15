"""Audio conversion API backed by the shared media worker."""

from __future__ import annotations

import json
import os
from functools import partial
from pathlib import Path

import anyio
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from ...core.errors import MediaProcessingError
from ...core.limits import RATE_LIMIT, limiter
from ...core.media.ffmpeg import audio_command, probe_media, run_ffmpeg
from ...core.media.jobs import copy_limited, manager, safe_filename
from ...core.media.models import AudioConvertOptions, MediaJobResponse, MediaJobStatusResponse
from ...core.media.security import validate_public_url
from ...core.media.worker import download_media, media_result

router = APIRouter(tags=["audio-convert"])
_JOB_KIND = "audio-convert"
_MAX_DURATION = int(os.getenv("TOOLBOX_MEDIA_MAX_DURATION_SECONDS", "7200"))
_MEDIA_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "m4a": "audio/mp4",
    "aac": "audio/aac",
    "flac": "audio/flac",
}


def _maybe_limit(fn):
    if not RATE_LIMIT:
        return fn
    return limiter.limit(RATE_LIMIT)(fn)


def _options(raw: str) -> AudioConvertOptions:
    try:
        return AudioConvertOptions.model_validate(json.loads(raw or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(422, "音频转换参数无效") from exc


def _check_duration(probe: dict) -> None:
    value = probe.get("format", {}).get("duration")
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return
    if duration > _MAX_DURATION:
        raise MediaProcessingError(f"媒体时长不能超过 {_MAX_DURATION} 秒")


@router.post("/jobs", response_model=MediaJobResponse)
@_maybe_limit
async def submit_job(
    request: Request,
    options: str = Form(default="{}"),
    file: UploadFile | None = File(default=None),
    url: str = Form(default=""),
):
    parsed_options = _options(options)
    has_file = file is not None
    has_url = bool(url.strip())
    if has_file == has_url:
        raise HTTPException(422, "请在音频文件和媒体网址之间选择一个")

    prepare = None
    filename = f"converted.{parsed_options.output_format}"
    if file is not None:
        original_name = safe_filename(file.filename, "audio.bin")
        input_name = "input" + (Path(original_name).suffix[:16] if Path(original_name).suffix else ".bin")

        def prepare_upload(work_dir: Path) -> None:
            try:
                copy_limited(file.file, work_dir / input_name)
            except ValueError as exc:
                raise HTTPException(413, "媒体文件超过大小限制") from exc

        def run_upload(work_dir: Path, cancelled, progress):
            source = work_dir / input_name
            if cancelled.is_set():
                raise MediaProcessingError("媒体任务已取消")
            probe = probe_media(source)
            _check_duration(probe)
            output = work_dir / filename
            run_ffmpeg(audio_command(source, output, parsed_options), cancel_event=cancelled)
            progress(100)
            return media_result(output, filename, _MEDIA_TYPES[parsed_options.output_format])

        prepare = prepare_upload
        runner = run_upload
    else:
        safe_url = await anyio.to_thread.run_sync(validate_public_url, url)

        def run_download(work_dir: Path, cancelled, progress):
            if cancelled.is_set():
                raise MediaProcessingError("媒体任务已取消")
            source = download_media(safe_url, work_dir, progress, cancelled)
            probe = probe_media(source)
            _check_duration(probe)
            output = work_dir / filename
            run_ffmpeg(audio_command(source, output, parsed_options), cancel_event=cancelled)
            progress(100)
            return media_result(output, filename, _MEDIA_TYPES[parsed_options.output_format])

        runner = run_download

    try:
        job_id = await anyio.to_thread.run_sync(
            partial(manager.submit, _JOB_KIND, runner, prepare)
        )
    except HTTPException:
        raise
    except RuntimeError as exc:
        message = "媒体任务队列已满，请稍后重试" if "too many" in str(exc) else "媒体任务无法启动"
        raise HTTPException(503, message) from exc
    return JSONResponse(MediaJobResponse(job_id=job_id, status="queued", progress=0).model_dump())


@router.get("/jobs/{job_id}", response_model=MediaJobStatusResponse)
def get_job_status(job_id: str):
    status = manager.status(job_id, kind=_JOB_KIND)
    if status is None:
        raise HTTPException(404, "任务不存在")
    return status


@router.delete("/jobs/{job_id}")
def cancel_job(job_id: str):
    if manager.cancel(job_id, kind=_JOB_KIND):
        return {"status": "cancelled"}
    if manager.remove(job_id, kind=_JOB_KIND):
        return {"status": "removed"}
    raise HTTPException(404, "任务不存在")


@router.get("/jobs/{job_id}/result")
def get_job_result(job_id: str):
    job = manager.get(job_id, kind=_JOB_KIND)
    if job is None or job.status.value != "done" or job.result is None:
        raise HTTPException(404, "任务未完成或不存在")
    result = job.result
    path = Path(result.path)
    if path.parent.resolve() != job.work_dir.resolve() or not path.is_file():
        manager.remove(job_id, kind=_JOB_KIND)
        raise HTTPException(404, "任务结果不存在")
    return FileResponse(
        path,
        filename=safe_filename(result.filename, "audio-result"),
        media_type=result.media_type,
        background=BackgroundTask(manager.remove, job_id, _JOB_KIND),
    )
