"""Vision-LLM credentials resolution.

Keys are user-owned and passed per-request from the browser (set via
`set_request_config` by the file-convert router) — nothing is written to
disk by this module. `CONFIG_PATH` is a legacy read-only fallback for
setups that hand-edited ``~/.toolbox/llm.json`` before the per-request
migration; new deployments never create it.
"""

import json
import os
import threading
from pathlib import Path
from typing import TypedDict

_data_dir = os.getenv("TOOLBOX_DATA_DIR", "")
CONFIG_DIR = (Path(_data_dir) if _data_dir else Path.home()) / ".toolbox"
CONFIG_PATH = CONFIG_DIR / "llm.json"

# Per-request override — set by the file-convert router when the user
# supplies their own LLM credentials in the job submission form.
_thread_local = threading.local()


def set_request_config(config: "LLMSettings | None") -> None:
    """Set (or clear) a per-thread LLM config that overrides the on-disk file."""
    _thread_local.config = config


class LLMSettings(TypedDict, total=False):
    provider: str  # provider id, e.g. "qwen"
    model: str
    api_key: str


def load() -> LLMSettings:
    """Return current LLM settings.

    Priority: per-request thread-local (user-supplied) > legacy on-disk file.
    """
    override = getattr(_thread_local, "config", None)
    if override:
        return override
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
