from __future__ import annotations

import io
import threading
import time
from types import SimpleNamespace

import pytest

from toolbox.core.media.jobs import MediaJobManager, copy_limited
from toolbox.core.media.models import MediaResult
from toolbox.core.media.security import (
    canonical_youtube_url,
    extract_youtube_id,
    validate_public_url,
)


def test_youtube_urls_are_canonicalized_without_query_data():
    assert extract_youtube_id("https://www.youtube.com/watch?v=abcdefghijk&si=secret") == "abcdefghijk"
    assert extract_youtube_id("https://youtu.be/abcdefghijk") == "abcdefghijk"
    assert extract_youtube_id("https://www.youtube.com/shorts/abcdefghijk") == "abcdefghijk"
    assert canonical_youtube_url("abcdefghijk") == "https://www.youtube.com/watch?v=abcdefghijk"


@pytest.mark.parametrize(
    "url",
    [
        "http://www.youtube.com/watch?v=abcdefghijk",
        "file:///tmp/video.mp4",
        "https://evil.example/watch?v=abcdefghijk",
        "https://user:pass@www.youtube.com/watch?v=abcdefghijk",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/watch?v=abcdefghijk#fragment",
        "https://youtu.be/abcdefghijk?token=secret",
    ],
)
def test_youtube_url_policy_rejects_unsafe_inputs(url: str):
    with pytest.raises(Exception):
        extract_youtube_id(url)


@pytest.mark.parametrize("host", ["127.0.0.1", "10.0.0.2", "::1", "169.254.169.254"])
def test_public_url_policy_rejects_private_addresses(host: str):
    with pytest.raises(Exception):
        validate_public_url(f"https://[{host}]" if ":" in host else f"https://{host}/video.mp4")


def test_public_url_policy_checks_all_dns_answers(monkeypatch):
    import toolbox.core.media.security as security

    monkeypatch.setattr(
        security.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (security.socket.AF_INET, security.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (security.socket.AF_INET, security.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(Exception):
        validate_public_url("https://media.example/video.mp4")


def test_copy_limited_enforces_stream_size(tmp_path):
    destination = tmp_path / "media.bin"
    assert copy_limited(io.BytesIO(b"abc"), destination, max_bytes=3) == 3
    assert destination.read_bytes() == b"abc"
    with pytest.raises(ValueError):
        copy_limited(io.BytesIO(b"abcd"), tmp_path / "too-large.bin", max_bytes=3)


def _wait_for(manager: MediaJobManager, job_id: str, expected: str = "done"):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        status = manager.status(job_id)
        if status and status["status"].value == expected:
            return status
        time.sleep(0.01)
    raise AssertionError(f"job did not reach {expected}: {manager.status(job_id)}")


def test_job_manager_isolates_kinds_and_cleans_result(tmp_path, monkeypatch):
    import toolbox.core.media.jobs as jobs

    monkeypatch.setattr(jobs, "MEDIA_DIR", tmp_path / "media")
    manager = MediaJobManager(max_workers=1)
    finished = threading.Event()

    def runner(work_dir, cancelled, progress):
        result = work_dir / "result.mp3"
        result.write_bytes(b"result")
        progress(100)
        finished.set()
        return MediaResult(str(result), "result.mp3", "audio/mpeg")

    try:
        job_id = manager.submit("audio-convert", runner)
        assert finished.wait(2)
        assert manager.status(job_id, kind="video-edit") is None
        assert manager.status(job_id, kind="audio-convert")["status"].value == "done"
        assert manager.remove(job_id, kind="video-edit") is False
        assert manager.remove(job_id, kind="audio-convert") is True
        assert manager.status(job_id, kind="audio-convert") is None
    finally:
        manager.shutdown()


def test_job_manager_cancel_is_terminal(tmp_path, monkeypatch):
    import toolbox.core.media.jobs as jobs

    monkeypatch.setattr(jobs, "MEDIA_DIR", tmp_path / "media")
    manager = MediaJobManager(max_workers=1)

    def runner(work_dir, cancelled, progress):
        while not cancelled.is_set():
            time.sleep(0.01)
        raise RuntimeError("cancelled")

    try:
        job_id = manager.submit("video-edit", runner)
        deadline = time.monotonic() + 2
        while manager.status(job_id)["status"].value == "queued" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert manager.cancel(job_id, kind="video-edit") is True
        assert manager.status(job_id, kind="video-edit")["status"].value == "cancelled"
    finally:
        manager.shutdown()


def test_video_metadata_uses_fixed_oembed(monkeypatch):
    from toolbox.core.media import worker

    calls: list[tuple[str, dict[str, str]]] = []

    def fake_json(url: str, params: dict[str, str]):
        calls.append((url, params))
        return {
            "title": "A title",
            "author_name": "An author",
            "thumbnail_url": "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg",
            "description": "ignored",
        }

    monkeypatch.setattr(worker, "_bounded_http_json", fake_json)
    result = worker.fetch_youtube_metadata("abcdefghijk")
    assert result.title == "A title"
    assert calls == [
        (
            "https://www.youtube.com/oembed",
            {"url": "https://www.youtube.com/watch?v=abcdefghijk", "format": "json"},
        )
    ]


def test_caption_segments_are_bounded(monkeypatch):
    from youtube_transcript_api import YouTubeTranscriptApi
    from toolbox.core.media import worker

    snippets = [SimpleNamespace(text="x" * 2_000, start=1, duration=2)] * 400

    class Fetched:
        language_code = "en"
        is_generated = True

        def __iter__(self):
            return iter(snippets)

    monkeypatch.setattr(
        YouTubeTranscriptApi,
        "fetch",
        lambda self, video_id, languages: Fetched(),
    )
    result = worker.fetch_youtube_captions("abcdefghijk", ["en"])
    assert result.language_code == "en"
    assert len(result.transcript) <= 500_000
    assert len(result.segments) <= 20_000


def test_media_routes_are_registered():
    from toolbox.api import api

    def paths(routes, prefix=""):
        found = set()
        for route in routes:
            path = getattr(route, "path", None)
            if path is not None:
                found.add(prefix + path)
            included = getattr(route, "original_router", None)
            if included is not None:
                context = getattr(route, "include_context", None)
                child_prefix = getattr(context, "prefix", "")
                found.update(paths(included.routes, prefix + child_prefix))
            else:
                found.update(paths(getattr(route, "routes", ()), prefix))
        return found

    registered = paths(api.routes)
    assert "/tools/video-extract/metadata" in registered
    assert "/tools/video-extract/captions" in registered
    assert "/tools/video-extract/jobs" in registered
    assert "/tools/audio-convert/jobs" in registered
    assert "/tools/video-edit/jobs" in registered
