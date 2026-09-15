"""Bounded, isolated media job lifecycle shared by media tools."""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .models import MediaJobStatus, MediaResult

MEDIA_DIR = Path(os.getenv("TOOLBOX_MEDIA_DIR", tempfile.gettempdir())) / "toolbox_media"
MAX_PENDING_JOBS = int(os.getenv("TOOLBOX_MEDIA_MAX_PENDING", "16"))
JOB_TTL_SECONDS = int(os.getenv("TOOLBOX_MEDIA_JOB_TTL", "1800"))
MAX_UPLOAD_BYTES = int(os.getenv("TOOLBOX_MEDIA_MAX_INPUT_MB", "200")) * 1024 * 1024

if MEDIA_DIR.exists() and MEDIA_DIR.is_symlink():
    raise RuntimeError(f"{MEDIA_DIR} is a symlink; refusing to write")
MEDIA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

Progress = Callable[[int], None]
JobRunner = Callable[[Path, threading.Event, Progress], MediaResult]
JobPrepare = Callable[[Path], None]


@dataclass
class _Job:
    job_id: str
    kind: str
    work_dir: Path
    created_at: float
    status: MediaJobStatus = MediaJobStatus.QUEUED
    progress: int = 0
    error: str | None = None
    result: MediaResult | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    future: Future | None = None


class MediaJobManager:
    def __init__(self, max_workers: int = 2):
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="toolbox-media")

    def submit(self, kind: str, runner: JobRunner, prepare: JobPrepare | None = None) -> str:
        self.sweep()
        with self._lock:
            pending = sum(
                job.status in {MediaJobStatus.QUEUED, MediaJobStatus.PROCESSING}
                for job in self._jobs.values()
            )
            if pending >= MAX_PENDING_JOBS:
                raise RuntimeError("too many media jobs")
            job_id = uuid.uuid4().hex
            work_dir = MEDIA_DIR / job_id
            MEDIA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
            work_dir.mkdir(mode=0o700)
            job = _Job(kind=kind, job_id=job_id, work_dir=work_dir, created_at=time.monotonic())
            self._jobs[job_id] = job

        try:
            if prepare is not None:
                prepare(work_dir)
            with self._lock:
                current = self._jobs.get(job_id)
                if current is None or current.cancel_event.is_set():
                    raise RuntimeError("media job cancelled")
                current.future = self._executor.submit(self._run, job_id, runner)
            return job_id
        except Exception:
            self.remove(job_id)
            raise

    def _run(self, job_id: str, runner: JobRunner) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if job.cancel_event.is_set():
                job.status = MediaJobStatus.CANCELLED
                return
            job.status = MediaJobStatus.PROCESSING

        def progress(value: int) -> None:
            with self._lock:
                current = self._jobs.get(job_id)
                if current and current.status == MediaJobStatus.PROCESSING:
                    current.progress = max(0, min(100, int(value)))

        try:
            result = runner(job.work_dir, job.cancel_event, progress)
            with self._lock:
                current = self._jobs.get(job_id)
                if current is None:
                    return
                if current.cancel_event.is_set():
                    current.status = MediaJobStatus.CANCELLED
                    current.result = None
                else:
                    current.result = result
                    current.progress = 100
                    current.status = MediaJobStatus.DONE
        except Exception as exc:
            with self._lock:
                current = self._jobs.get(job_id)
                if current is not None:
                    current.status = MediaJobStatus.CANCELLED if current.cancel_event.is_set() else MediaJobStatus.FAILED
                    current.error = "媒体任务已取消" if current.cancel_event.is_set() else _safe_error(exc)
        finally:
            with self._lock:
                current = self._jobs.get(job_id)
                should_cleanup = current is not None and current.status == MediaJobStatus.CANCELLED
            if should_cleanup:
                shutil.rmtree(job.work_dir, ignore_errors=True)

    def get(self, job_id: str, kind: str | None = None) -> _Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and kind is not None and job.kind != kind:
                return None
            return job

    def cancel(self, job_id: str, kind: str | None = None) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or (kind is not None and job.kind != kind):
                return False
            if job.status in {MediaJobStatus.DONE, MediaJobStatus.FAILED, MediaJobStatus.CANCELLED}:
                return False
            job.cancel_event.set()
            job.status = MediaJobStatus.CANCELLED
            future = job.future
            if future is not None:
                future.cancel()
        shutil.rmtree(job.work_dir, ignore_errors=True)
        return True

    def remove(self, job_id: str, kind: str | None = None) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or (kind is not None and job.kind != kind):
                return False
            self._jobs.pop(job_id, None)
        job.cancel_event.set()
        if job.future is not None:
            job.future.cancel()
        shutil.rmtree(job.work_dir, ignore_errors=True)
        return True

    def sweep(self) -> None:
        cutoff = time.monotonic() - JOB_TTL_SECONDS
        with self._lock:
            expired = [job_id for job_id, job in self._jobs.items() if job.created_at < cutoff]
        for job_id in expired:
            self.remove(job_id)

    def startup_cleanup(self) -> None:
        with self._lock:
            self._jobs.clear()
        shutil.rmtree(MEDIA_DIR, ignore_errors=True)
        MEDIA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        with self._lock:
            jobs = list(self._jobs)
        for job_id in jobs:
            self.remove(job_id)

    def status(self, job_id: str, kind: str | None = None) -> dict | None:
        job = self.get(job_id, kind=kind)
        if job is None:
            return None
        with self._lock:
            return {
                "job_id": job.job_id,
                "status": job.status,
                "progress": job.progress,
                "error": job.error,
                "filename": job.result.filename if job.result else None,
                "media_type": job.result.media_type if job.result else None,
            }


def copy_limited(source, destination: Path, max_bytes: int = MAX_UPLOAD_BYTES) -> int:
    """Copy an upload while enforcing a hard byte limit independent of headers."""
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    total = 0
    with destination.open("wb") as output:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("媒体输入文件过大")
            output.write(chunk)
    return total


def safe_filename(raw: str | None, fallback: str = "media") -> str:
    name = Path((raw or "").replace("\\", "/")).name
    if not name or name in {".", ".."} or "\x00" in name:
        return fallback
    return name[:180]


def _safe_error(exc: Exception) -> str:
    text = str(exc).replace("\n", " ").strip()
    return text[:500] or "媒体任务失败"


manager = MediaJobManager()
