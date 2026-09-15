"""Video crop and trim API backed by FFmpeg."""

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
from ...core.media.ffmpeg import probe_media, run_ffmpeg, video_edit_command
from ...core.media.jobs import copy_limited, manager, safe_filename
from ...core.media.models import CropOptions, MediaJobResponse, MediaJobStatusResponse
from ...core.media.security import validate_public_url
from ...core.media.worker import download_media, media_result

router = APIRouter(tags=["video-edit"])
_JOB_KIND = "video-edit"
_MAX_DURATION = int(os.getenv("TOOLBOX_MEDIA_MAX_DURATION_SECONDS", "7200"))


def _maybe_limit(fn):
    if not RATE_LIMIT:
        return fn
    return limiter.limit(RATE_LIMIT)(fn)


def _options(raw: str) -> CropOptions:
    try:
        options = CropOptions.model_validate(json.loads(raw or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(422, "视频编辑参数无效") from exc
    if options.action == "crop" and (options.x + options.width > 1 or options.y + options.height > 1):
        raise HTTPException(422, "裁剪区域必须位于视频范围内")
    if options.end is not None and options.end <= options.start:
        raise HTTPException(422, "结束时间必须大于开始时间")
    return options


def _probe_dimensions(probe: dict) -> tuple[int, int]:
    streams = probe.get("streams")
    if not isinstance(streams, list):
        raise MediaProcessingError("无法读取视频尺寸")
    for stream in streams:
        if isinstance(stream, dict) and stream.get("codec_type") == "video":
            try:
                width, height = int(stream["width"]), int(stream["height"])
            except (KeyError, TypeError, ValueError) as exc:
                raise MediaProcessingError("无法读取视频尺寸") from exc
            if width > 0 and height > 0:
                return width, height
    raise MediaProcessingError("输入文件不包含视频轨道")


def _check_duration(probe: dict) -> None:
    try:
        duration = float(probe.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        return
    if duration > _MAX_DURATION:
        raise MediaProcessingError(f"媒体时长不能超过 {_MAX_DURATION} 秒")


def _edit_runner(source_name: str, options: CropOptions):
    def run(work_dir: Path, cancelled, progress):
        source = work_dir / source_name
        if cancelled.is_set():
            raise MediaProcessingError("媒体任务已取消")
        probe = probe_media(source)
        _check_duration(probe)
        width, height = _probe_dimensions(probe)
        output_name = "edited.mp4"
        output = work_dir / output_name
        run_ffmpeg(video_edit_command(source, output, options, width, height), cancel_event=cancelled)
        progress(100)
        return media_result(output, output_name, "video/mp4")

    return run


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
        raise HTTPException(422, "请在视频文件和媒体网址之间选择一个")

    prepare = None
    if file is not None:
        original_name = safe_filename(file.filename, "video.bin")
        input_name = "input" + (Path(original_name).suffix[:16] if Path(original_name).suffix else ".bin")

        def prepare_upload(work_dir: Path) -> None:
            try:
                copy_limited(file.file, work_dir / input_name)
            except ValueError as exc:
                raise HTTPException(413, "媒体文件超过大小限制") from exc

        prepare = prepare_upload
        runner = _edit_runner(input_name, parsed_options)
    else:
        safe_url = await anyio.to_thread.run_sync(validate_public_url, url)

        def run_download(work_dir: Path, cancelled, progress):
            if cancelled.is_set():
                raise MediaProcessingError("媒体任务已取消")
            source = download_media(safe_url, work_dir, progress, cancelled)
            return _edit_runner(source.name, parsed_options)(work_dir, cancelled, progress)

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
        filename=safe_filename(result.filename, "video-result.mp4"),
        media_type=result.media_type,
        background=BackgroundTask(manager.remove, job_id, _JOB_KIND),
    )
