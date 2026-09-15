"""Video URL metadata, captions, and bounded download routes."""

from __future__ import annotations

from functools import partial
from pathlib import Path

import anyio
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from ...core.errors import MediaProcessingError
from ...core.limits import RATE_LIMIT, limiter
from ...core.media.ffmpeg import probe_media
from ...core.media.jobs import copy_limited, manager, safe_filename
from ...core.media.models import CaptionsResponse, MetadataResponse, MediaJobResponse, MediaJobStatusResponse, VideoUrlRequest
from ...core.media.security import extract_youtube_id, validate_public_url
from ...core.media.worker import download_media, fetch_youtube_captions, fetch_youtube_metadata, media_result

router = APIRouter(tags=["video-extract"])
_JOB_KIND = "video-extract"


def _maybe_limit(fn):
    if not RATE_LIMIT:
        return fn
    return limiter.limit(RATE_LIMIT)(fn)


@router.post("/metadata", response_model=MetadataResponse)
@_maybe_limit
async def metadata(request: Request, payload: VideoUrlRequest):
    video_id = extract_youtube_id(payload.url)
    data = await anyio.to_thread.run_sync(fetch_youtube_metadata, video_id)
    return JSONResponse(MetadataResponse(metadata=data).model_dump())


@router.post("/captions", response_model=CaptionsResponse)
@_maybe_limit
async def captions(request: Request, payload: VideoUrlRequest):
    video_id = extract_youtube_id(payload.url)
    result = await anyio.to_thread.run_sync(fetch_youtube_captions, video_id, payload.languages)
    return JSONResponse(result.model_dump())


@router.post("/jobs", response_model=MediaJobResponse)
@_maybe_limit
async def submit_job(
    request: Request,
    file: UploadFile | None = File(default=None),
    url: str = Form(default=""),
):
    has_file = file is not None
    has_url = bool(url.strip())
    if has_file == has_url:
        raise HTTPException(422, "请在文件和视频网址之间选择一个")

    runner = None
    prepare = None
    filename = "video.bin"
    if file is not None:
        filename = safe_filename(file.filename, "video.bin")
        input_name = "input" + (Path(filename).suffix[:16] if Path(filename).suffix else ".bin")

        def prepare_upload(work_dir: Path) -> None:
            try:
                copy_limited(file.file, work_dir / input_name)
            except ValueError as exc:
                raise HTTPException(413, "媒体文件超过大小限制") from exc

        def run_upload(work_dir: Path, cancelled, progress):
            source = work_dir / input_name
            if cancelled.is_set():
                raise MediaProcessingError("媒体任务已取消")
            probe_media(source)
            progress(100)
            return media_result(source, filename, file.content_type or "application/octet-stream")

        prepare = prepare_upload
        runner = run_upload
    else:
        safe_url = await anyio.to_thread.run_sync(validate_public_url, url)
        filename = "downloaded-media"

        def run_download(work_dir: Path, cancelled, progress):
            if cancelled.is_set():
                raise MediaProcessingError("媒体任务已取消")
            source = download_media(safe_url, work_dir, progress, cancelled)
            return media_result(source, source.name, "application/octet-stream")

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
        filename=safe_filename(result.filename, "media-result"),
        media_type=result.media_type,
        background=BackgroundTask(manager.remove, job_id, _JOB_KIND),
    )
