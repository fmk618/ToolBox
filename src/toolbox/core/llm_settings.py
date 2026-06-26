"""User-configurable Vision-LLM settings.

Stored as JSON at ``~/.toolbox/llm.json`` with 0600 permission. Holds the
currently active provider id, model name, and API key. Read at every
conversion request so settings can be changed without restarting the backend.
"""

import json
import os
import stat
from pathlib import Path
from typing import TypedDict

_data_dir = os.getenv("TOOLBOX_DATA_DIR", "")
CONFIG_DIR = (Path(_data_dir) if _data_dir else Path.home()) / ".toolbox"
CONFIG_PATH = CONFIG_DIR / "llm.json"


class LLMSettings(TypedDict, total=False):
    provider: str  # provider id, e.g. "qwen"
    model: str
    api_key: str


def load() -> LLMSettings:
    """Read settings from disk; return {} if not configured yet."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save(settings: LLMSettings) -> None:
    """Atomically write settings to disk with restrictive permissions."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 0600 owner only
    tmp.replace(CONFIG_PATH)


def public_view(settings: LLMSettings) -> dict:
    """Strip the API key for safe API responses; expose only whether one is set."""
    key = settings.get("api_key", "")
    return {
        "provider": settings.get("provider"),
        "model": settings.get("model"),
        "has_key": bool(key),
        "key_preview": (
            f"{key[:4]}…{key[-4:]}" if len(key) >= 12 else ""
        ),
    }


def clear() -> None:
    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()
