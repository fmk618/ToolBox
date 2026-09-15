"""Network-backed metadata/caption services and the bounded yt-dlp adapter."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Iterable

import httpx
from requests import Session

from ..errors import MediaProcessingError, MediaUnavailableError
from .ffmpeg import FFMPEG_BIN
from .models import CaptionSegment, CaptionsResponse, MediaResult, VideoMetadata
from .security import canonical_youtube_url

_OEMBED_URL = "https://www.youtube.com/oembed"
_MAX_RESPONSE_BYTES = 512 * 1024
_MAX_CAPTION_BYTES = 4 * 1024 * 1024
_MAX_SEGMENTS = 20_000
_MAX_TRANSCRIPT_CHARS = 500_000


def _bounded_http_json(url: str, params: dict[str, str]) -> dict:
    try:
        with httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", url, params=params, headers={"Accept": "application/json"}) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if "json" not in content_type:
                    raise MediaProcessingError("远程元数据格式无效")
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes(64 * 1024):
                    size += len(chunk)
                    if size > _MAX_RESPONSE_BYTES:
                        raise MediaProcessingError("远程元数据过大")
                    chunks.append(chunk)
    except httpx.TimeoutException as exc:
        raise MediaProcessingError("获取视频元数据超时") from exc
    except httpx.HTTPError as exc:
        raise MediaProcessingError("无法获取视频元数据") from exc
    try:
        value = json.loads(b"".join(chunks))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MediaProcessingError("远程元数据无效") from exc
    if not isinstance(value, dict):
        raise MediaProcessingError("远程元数据无效")
    return value


def _text(value: object, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def fetch_youtube_metadata(video_id: str) -> VideoMetadata:
    canonical = canonical_youtube_url(video_id)
    data = _bounded_http_json(_OEMBED_URL, {"url": canonical, "format": "json"})
    title = _text(data.get("title"), 500)
    author = _text(data.get("author_name"), 300)
    thumbnail = _text(data.get("thumbnail_url"), 2_048) or None
    return VideoMetadata(
        video_id=video_id,
        title=title,
        author=author,
        thumbnail_url=thumbnail,
        source_url=canonical,
    )


class _BoundedSession(Session):
    """Give youtube-transcript-api both timeouts and a response byte ceiling."""

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", (10, 30))
        kwargs["stream"] = True
        response = super().request(method, url, **kwargs)
        total = 0
        chunks: list[bytes] = []
        for chunk in response.iter_content(64 * 1024):
            total += len(chunk)
            if total > _MAX_CAPTION_BYTES:
                response.close()
                raise MediaProcessingError("字幕响应过大")
            chunks.append(chunk)
        response._content = b"".join(chunks)
        response.close()
        return response


def fetch_youtube_captions(video_id: str, languages: Iterable[str]) -> CaptionsResponse:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import (
            NoTranscriptFound,
            TranscriptsDisabled,
            VideoUnavailable,
        )
    except ImportError as exc:
        raise MediaUnavailableError("字幕功能依赖未安装") from exc

    selected_languages = [str(item).strip()[:32] for item in languages if str(item).strip()][:8] or ["en"]
    try:
        fetched = YouTubeTranscriptApi(http_client=_BoundedSession()).fetch(video_id, languages=selected_languages)
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable):
        return CaptionsResponse(
            video_id=video_id,
            warnings=["该视频没有可用字幕，或字幕暂不可访问"],
        )
    except MediaProcessingError:
        raise
    except Exception as exc:
        raise MediaProcessingError("获取视频字幕失败") from exc

    segments: list[CaptionSegment] = []
    text_parts: list[str] = []
    total_chars = 0
    for snippet in fetched:
        text = _text(getattr(snippet, "text", ""), 2_000)
        if not text:
            continue
        start = max(0.0, min(86_400.0, float(getattr(snippet, "start", 0))))
        duration = max(0.0, float(getattr(snippet, "duration", 0)))
        end = min(86_400.0, start + duration)
        if end < start:
            end = start
        remaining = _MAX_TRANSCRIPT_CHARS - total_chars
        if remaining <= 0:
            break
        text = text[:remaining]
        segments.append(CaptionSegment(start=start, end=end, text=text))
        text_parts.append(text)
        total_chars += len(text) + 1
        if len(segments) >= _MAX_SEGMENTS:
            break

    transcript = "\n".join(text_parts)[:_MAX_TRANSCRIPT_CHARS]
    return CaptionsResponse(
        video_id=video_id,
        language_code=getattr(fetched, "language_code", None),
        is_generated=getattr(fetched, "is_generated", None),
        segments=segments,
        transcript=transcript,
        transcript_source="caption" if transcript else "none",
        warnings=["字幕内容已按安全上限截断"] if total_chars >= _MAX_TRANSCRIPT_CHARS else [],
    )


def download_media(
    url: str,
    work_dir: Path,
    progress,
    cancelled: threading.Event | None = None,
) -> Path:
    """Download one public media URL through yt-dlp with fixed safe options."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise MediaUnavailableError("视频下载依赖未安装") from exc

    max_bytes = int(os.getenv("TOOLBOX_MEDIA_MAX_DOWNLOAD_MB", "500")) * 1024 * 1024
    max_seconds = int(os.getenv("TOOLBOX_MEDIA_MAX_DURATION_SECONDS", "7200"))
    template = str(work_dir / "source.%(ext)s")

    def hook(info: dict) -> None:
        if cancelled is not None and cancelled.is_set():
            raise MediaProcessingError("媒体任务已取消")
        if info.get("status") == "downloading":
            total = info.get("total_bytes") or info.get("total_bytes_estimate")
            downloaded = info.get("downloaded_bytes", 0)
            if total:
                progress(min(80, int(downloaded / total * 80)))

    def match_filter(info: dict, incomplete: bool):
        duration = info.get("duration")
        if duration is not None and duration > max_seconds:
            return f"视频时长超过 {max_seconds} 秒"
        return None

    options = {
        "format": "bestvideo*+bestaudio/best",
        "outtmpl": template,
        "noplaylist": True,
        "max_filesize": max_bytes,
        "socket_timeout": 20,
        "retries": 1,
        "fragment_retries": 1,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "progress_hooks": [hook],
        "match_filter": match_filter,
        "paths": {"home": str(work_dir)},
        "ffmpeg_location": str(Path(FFMPEG_BIN).parent) if "/" in FFMPEG_BIN else None,
    }
    options = {key: value for key, value in options.items() if value is not None}
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
            prepared = Path(downloader.prepare_filename(info))
    except Exception as exc:
        raise MediaProcessingError("下载视频失败") from exc

    candidates = [path for path in work_dir.iterdir() if path.is_file() and path.name.startswith("source.")]
    if prepared.is_file() and prepared.parent == work_dir:
        result = prepared
    elif candidates:
        result = max(candidates, key=lambda item: item.stat().st_size)
    else:
        raise MediaProcessingError("下载完成但未找到媒体文件")
    if result.stat().st_size > max_bytes:
        raise MediaProcessingError("下载文件超过大小限制")
    progress(85)
    return result


def media_result(path: Path, filename: str, media_type: str) -> MediaResult:
    if not path.is_file():
        raise MediaProcessingError("媒体输出文件不存在")
    return MediaResult(str(path), filename, media_type)
