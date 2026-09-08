"""Security regression tests for the HTTP API.

Each test locks in a fix from the 2026-09 security review:
- upload filename path traversal  (was: arbitrary file write)
- upload size cap on /jobs        (was: only /convert was capped)
- rate limit per real client IP   (was: every user shared one bucket)
- target-format whitelist         (was: `to` reached the filesystem unchecked)
- ToolboxError → HTTP status mapping
- job TTL reaper + startup cleanup
"""

import tempfile
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from toolbox.api import api
from toolbox.core.errors import (
    ConversionFailedError,
    EngineNotAvailableError,
    NoConversionPathError,
    UnknownFormatError,
)
from toolbox.tools.file_convert.router import (
    _OUTPUT_DIR,
    _jobs,
    _jobs_lock,
    _sweep_expired_jobs,
    startup_cleanup,
)

# No `with` — skip lifespan so tests don't trigger the Docling model warmup.
client = TestClient(api)


@pytest.fixture(autouse=True)
def _fresh_rate_limit_bucket():
    """Give every test an empty rate-limit bucket (in-process storage)."""
    from toolbox.core.limits import limiter

    storage = getattr(limiter, "_storage", None)
    if storage is not None:
        storage.reset()
    yield


def _submit(name: str, content: bytes, to: str = "txt"):
    return client.post(
        "/tools/file-convert/jobs",
        params={"to": to},
        files={"file": (name, content, "text/plain")},
    )


def _wait_done(job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/tools/file-convert/jobs/{job_id}").json()
        if body["status"] in {"done", "failed"}:
            return body
        time.sleep(0.05)
    raise AssertionError("job did not finish in time")


# ---------------------------------------------------------------------------
# C1 — upload filename path traversal
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "evil_name",
    [
        "../../pwned_traversal.txt",
        "/abs/../../pwned_abs.txt",
        "sub/dir/pwned_nested.txt",
    ],
)
def test_upload_filename_traversal_is_neutralized(evil_name):
    r = _submit(evil_name, b"hello toolbox")
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]

    body = _wait_done(job_id)
    assert body["status"] == "done", body

    got = client.get(f"/tools/file-convert/jobs/{job_id}/result")
    assert got.status_code == 200
    # Content-Disposition must carry a bare filename, no directory components.
    assert ".." not in got.headers.get("content-disposition", "")
    assert "/" not in got.headers.get("content-disposition", "").split("=")[-1]

    # Download triggers cleanup: job entry and files are gone.
    assert job_id not in _jobs
    assert not (_OUTPUT_DIR / job_id).exists()

    # Nothing escaped the job work dir into the shared temp root.
    tmp_root = Path(tempfile.gettempdir())
    assert not (tmp_root / "pwned_traversal.txt").exists()
    assert not (tmp_root / "pwned_abs.txt").exists()
    assert not (tmp_root / "pwned_nested.txt").exists()


def test_upload_rejects_empty_and_dot_names():
    assert _submit("..", b"x").status_code == 400
    # Empty filename is rejected even earlier by FastAPI's multipart validation.
    assert _submit("", b"x").status_code in (400, 422)
    assert _submit("dots/..", b"x").status_code == 400


# ---------------------------------------------------------------------------
# `to` — target format whitelist
# ---------------------------------------------------------------------------

def test_target_format_whitelist():
    assert _submit("a.txt", b"x", to="../../pwn").status_code == 422
    assert _submit("a.txt", b"x", to="exe").status_code == 422
    assert _submit("a.txt", b"x", to=".MD").status_code == 200  # normalized ok


# ---------------------------------------------------------------------------
# C3 — upload size cap applies to /jobs (and every /tools/ POST)
# ---------------------------------------------------------------------------

def test_upload_size_cap_applies_to_jobs():
    big = b"0" * (2 * 1024 * 1024)  # 2 MB > 1 MB cap set in conftest
    r = client.post(
        "/tools/file-convert/jobs",
        params={"to": "txt"},
        files={"file": ("big.txt", big, "text/plain")},
    )
    assert r.status_code == 413


# ---------------------------------------------------------------------------
# H5 — rate limiting keyed on real client IP
# ---------------------------------------------------------------------------

def test_client_ip_key_function():
    from toolbox.core.limits import client_ip

    req = type("Req", (), {})()
    req.client = type("Addr", (), {"host": "203.0.113.9"})()
    assert client_ip(req) == "203.0.113.9"
    req.client = None
    assert client_ip(req) == "127.0.0.1"


def test_rate_limit_returns_429_with_retry_after():
    for i in range(3):  # conftest sets TOOLBOX_RATE_LIMIT=3/minute
        r = _submit(f"rl-{i}.txt", b"hi")
        assert r.status_code == 200, r.text
    fourth = _submit("rl-4.txt", b"hi")
    assert fourth.status_code == 429
    assert "retry-after" in {k.lower() for k in fourth.headers.keys()}


# ---------------------------------------------------------------------------
# M2 — ToolboxError → HTTP status mapping
# ---------------------------------------------------------------------------

def test_error_status_mapping_table():
    assert UnknownFormatError.status_code == 415
    assert NoConversionPathError.status_code == 422
    assert EngineNotAvailableError.status_code == 503
    assert ConversionFailedError.status_code == 400


def test_unknown_format_maps_to_415():
    r = client.post(
        "/tools/file-convert/convert",
        params={"to": "txt"},
        files={"file": ("x.qqq", b"junk", "application/octet-stream")},
    )
    assert r.status_code == 415


# ---------------------------------------------------------------------------
# H1 — job TTL reaper + startup cleanup
# ---------------------------------------------------------------------------

def test_expired_jobs_are_reaped():
    r = _submit(f"ttl-{uuid.uuid4().hex}.txt", b"hi")
    job_id = r.json()["job_id"]
    assert _wait_done(job_id)["status"] == "done"

    with _jobs_lock:
        _jobs[job_id]["created_at"] = time.monotonic() - 7200
    _sweep_expired_jobs()

    assert job_id not in _jobs
    assert not (_OUTPUT_DIR / job_id).exists()


def test_startup_cleanup_wipes_stale_dirs():
    stale = _OUTPUT_DIR / "deadbeefdeadbeef"
    stale.mkdir(parents=True, exist_ok=True)
    (stale / "leftover.txt").write_bytes(b"x")

    startup_cleanup()

    assert not stale.exists()
    assert _OUTPUT_DIR.exists()


# ---------------------------------------------------------------------------
# Path planning (stubbed engines — must not depend on local pandoc/JVM)
# ---------------------------------------------------------------------------

class _StubEngine:
    def __init__(self, name, edges):
        self.name = name
        self._edges = edges

    @property
    def available(self):
        return True

    def edges(self):
        return list(self._edges)


def test_find_path_prefers_shortest_multihop(monkeypatch):
    from toolbox.core import engines_graph as eg

    # Mirror the real design: no single engine has a direct md→pdf edge;
    # md→docx then docx→pdf is the intended two-hop route.
    monkeypatch.setattr(
        eg,
        "ENGINES",
        [_StubEngine("md_engine", [("md", "docx")]),
         _StubEngine("pdf_engine", [("docx", "pdf")])],
    )
    steps = eg.find_path("md", "pdf")
    assert [(f, t) for f, t, _ in steps] == [("md", "docx"), ("docx", "pdf")]
    assert ("md", "pdf") not in [(f, t) for f, t, _ in steps]


def test_find_path_same_format_is_noop(monkeypatch):
    from toolbox.core import engines_graph as eg

    monkeypatch.setattr(eg, "ENGINES", [_StubEngine("a", [("txt", "md")])])
    assert eg.find_path("txt", "txt") == []


def test_find_path_unreachable_raises(monkeypatch):
    from toolbox.core import engines_graph as eg

    monkeypatch.setattr(eg, "ENGINES", [_StubEngine("a", [("txt", "md")])])
    with pytest.raises(NoConversionPathError):
        eg.find_path("md", "txt")
