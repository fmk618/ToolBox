"""Small, allowlisted wrappers around the system FFmpeg binaries."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Sequence

from ..errors import MediaProcessingError, MediaUnavailableError
from .models import AudioConvertOptions, CropOptions

FFMPEG_BIN = os.getenv("TOOLBOX_FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = os.getenv("TOOLBOX_FFPROBE_BIN", "ffprobe")
DEFAULT_TIMEOUT_SECONDS = 600


def _check_paths(input_path: Path, output_path: Path) -> None:
    if not input_path.is_file():
        raise MediaProcessingError("媒体输入文件不存在")
    output_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    root = output_path.parent.resolve()
    if output_path.resolve().parent != root or input_path.resolve().parent != root:
        raise MediaProcessingError("媒体路径无效")
    if input_path.resolve() == output_path.resolve():
        raise MediaProcessingError("输入和输出文件不能相同")


def _kill_process(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        process.kill()


def _run(
    argv: Sequence[str],
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    cancel_event: threading.Event | None = None,
) -> str:
    try:
        process = subprocess.Popen(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise MediaUnavailableError("服务器未安装 FFmpeg/FFprobe") from exc
    except OSError as exc:
        raise MediaUnavailableError("无法启动媒体处理程序") from exc

    try:
        if cancel_event is None:
            _, stderr = process.communicate(timeout=timeout)
        else:
            deadline = time.monotonic() + timeout
            while True:
                if cancel_event.is_set():
                    _kill_process(process)
                    process.communicate()
                    raise MediaProcessingError("媒体任务已取消")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _kill_process(process)
                    process.communicate()
                    raise MediaProcessingError("媒体处理超时")
                try:
                    _, stderr = process.communicate(timeout=min(0.2, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
    except subprocess.TimeoutExpired as exc:
        _kill_process(process)
        process.communicate()
        raise MediaProcessingError("媒体处理超时") from exc
    if process.returncode != 0:
        detail = (stderr or "").strip()[-500:]
        raise MediaProcessingError("媒体处理失败" + (f": {detail}" if detail else ""))
    return stderr or ""


def probe_media(path: Path, timeout: int = 60) -> dict:
    """Return bounded ffprobe JSON for duration and stream dimensions."""
    if not path.is_file():
        raise MediaProcessingError("媒体输入文件不存在")
    try:
        process = subprocess.Popen(
            [
                FFPROBE_BIN,
                "-v",
                "error",
                "-show_entries",
                "format=duration,size:stream=index,codec_type,width,height,channels,sample_rate",
                "-of",
                "json",
                str(path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise MediaUnavailableError("服务器未安装 FFprobe") from exc
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()
        process.communicate()
        raise MediaProcessingError("媒体探测超时") from exc
    if process.returncode != 0:
        raise MediaProcessingError("无法读取媒体信息")
    if len(stdout) > 128_000:
        raise MediaProcessingError("媒体探测结果过大")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise MediaProcessingError("媒体探测结果无效") from exc
    if not isinstance(data, dict):
        raise MediaProcessingError("媒体探测结果无效")
    return data


def audio_command(input_path: Path, output_path: Path, options: AudioConvertOptions) -> list[str]:
    _check_paths(input_path, output_path)
    codec = {
        "mp3": ["-vn", "-c:a", "libmp3lame", "-b:a", options.bitrate],
        "wav": ["-vn", "-c:a", "pcm_s16le"],
        "m4a": ["-vn", "-c:a", "aac", "-b:a", options.bitrate],
        "aac": ["-vn", "-c:a", "aac", "-b:a", options.bitrate],
        "flac": ["-vn", "-c:a", "flac"],
    }[options.output_format]
    audio = list(codec)
    if options.sample_rate != "source":
        audio.extend(["-ar", options.sample_rate])
    if options.channels != "source":
        audio.extend(["-ac", options.channels])
    return [FFMPEG_BIN, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i", str(input_path), *audio, str(output_path)]


def video_edit_command(
    input_path: Path,
    output_path: Path,
    options: CropOptions,
    width: int,
    height: int,
) -> list[str]:
    _check_paths(input_path, output_path)
    if width < 1 or height < 1:
        raise MediaProcessingError("无法读取视频尺寸")
    if options.action == "crop":
        crop_width = max(2, int(width * options.width) // 2 * 2)
        crop_height = max(2, int(height * options.height) // 2 * 2)
        crop_x = max(0, min(width - crop_width, int(width * options.x) // 2 * 2))
        crop_y = max(0, min(height - crop_height, int(height * options.y) // 2 * 2))
        filters = f"crop={crop_width}:{crop_height}:{crop_x}:{crop_y}"
    else:
        filters = "null"
    args = [FFMPEG_BIN, "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
    if options.start:
        args.extend(["-ss", f"{options.start:.3f}"])
    args.extend(["-i", str(input_path)])
    if options.end is not None:
        end = options.end
        if end <= options.start:
            raise MediaProcessingError("结束时间必须大于开始时间")
        args.extend(["-t", f"{end - options.start:.3f}"])
    args.extend(["-vf", filters, "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart", str(output_path)])
    return args


def run_ffmpeg(
    argv: Sequence[str],
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    cancel_event: threading.Event | None = None,
) -> None:
    _run(argv, timeout=timeout, cancel_event=cancel_event)
