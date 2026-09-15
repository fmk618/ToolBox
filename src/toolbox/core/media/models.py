"""Shared request and response models for media tools."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MediaJobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class VideoUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)
    languages: list[str] = Field(default_factory=lambda: ["zh-Hans", "zh", "en"], max_length=8)


class CaptionSegment(BaseModel):
    start: float = Field(ge=0, le=86_400)
    end: float = Field(ge=0, le=86_400)
    text: str = Field(min_length=1, max_length=2_000)


class VideoMetadata(BaseModel):
    video_id: str = Field(min_length=1, max_length=32)
    title: str = Field(default="", max_length=500)
    author: str = Field(default="", max_length=300)
    thumbnail_url: str | None = Field(default=None, max_length=2_048)
    source_url: str = Field(max_length=2_048)
    duration: float | None = Field(default=None, ge=0, le=86_400)
    provider: str = Field(default="youtube", max_length=40)


class MetadataResponse(BaseModel):
    metadata: VideoMetadata
    warnings: list[str] = Field(default_factory=list, max_length=16)


class CaptionsResponse(BaseModel):
    video_id: str
    language_code: str | None = None
    is_generated: bool | None = None
    segments: list[CaptionSegment] = Field(default_factory=list, max_length=20_000)
    transcript: str = Field(default="", max_length=500_000)
    transcript_source: Literal["caption", "none"] = "none"
    warnings: list[str] = Field(default_factory=list, max_length=16)


class MediaJobResponse(BaseModel):
    job_id: str
    status: MediaJobStatus
    progress: int = Field(ge=0, le=100)


class MediaJobStatusResponse(MediaJobResponse):
    error: str | None = None
    filename: str | None = None
    media_type: str | None = None


class AudioConvertOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_format: Literal["mp3", "wav", "m4a", "aac", "flac"] = "mp3"
    bitrate: Literal["96k", "128k", "192k", "256k", "320k"] = "192k"
    sample_rate: Literal["source", "8000", "16000", "22050", "44100", "48000"] = "source"
    channels: Literal["source", "1", "2"] = "source"


class CropOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["crop", "trim"] = "crop"
    x: float = Field(default=0, ge=0, le=1)
    y: float = Field(default=0, ge=0, le=1)
    width: float = Field(default=1, gt=0, le=1)
    height: float = Field(default=1, gt=0, le=1)
    start: float = Field(default=0, ge=0, le=86_400)
    end: float | None = Field(default=None, gt=0, le=86_400)


class MediaResult:
    """Internal worker result; API response models stay independent of paths."""

    def __init__(self, path: str, filename: str, media_type: str):
        self.path = path
        self.filename = filename
        self.media_type = media_type
