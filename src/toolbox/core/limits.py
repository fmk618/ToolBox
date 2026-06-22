"""Rate limiting + upload size limits, both env-driven.

Self-host defaults are generous;商用 deploys override via env vars before
exposing the API to the public internet.

Env vars
--------
TOOLBOX_RATE_LIMIT
    Slowapi-syntax limit applied per-IP to expensive endpoints
    (currently `/tools/file-convert/convert`). Example: "10/minute",
    "200/hour", "1/second;30/minute" (semicolon-joined). Empty disables.
    Default: "20/minute".

TOOLBOX_MAX_UPLOAD_MB
    Per-request body size cap in megabytes. Requests exceeding this are
    rejected with HTTP 413 before the engine touches them. Default: 100.
"""

from __future__ import annotations

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

_DEFAULT_RATE = "20/minute"
_DEFAULT_MAX_MB = 100

RATE_LIMIT = os.getenv("TOOLBOX_RATE_LIMIT", _DEFAULT_RATE).strip()
MAX_UPLOAD_MB = int(os.getenv("TOOLBOX_MAX_UPLOAD_MB", str(_DEFAULT_MAX_MB)))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# Limiter is enabled either way; routes without `@limiter.limit(...)` are
# unaffected. Setting TOOLBOX_RATE_LIMIT="" disables limits on annotated routes
# because slowapi treats an empty string as "no limit".
limiter = Limiter(key_func=get_remote_address)
