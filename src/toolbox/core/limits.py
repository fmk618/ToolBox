"""Rate limiting + upload size limits, both env-driven.

Self-host defaults are generous;商用 deploys override via env vars before
exposing the API to the public internet.

Env vars
--------
TOOLBOX_RATE_LIMIT
    Slowapi-syntax limit applied per-IP to expensive endpoints
    (currently the file-convert routes). Example: "10/minute",
    "200/hour", "1/second;30/minute" (semicolon-joined). Empty disables.
    Default: "20/minute".

TOOLBOX_MAX_UPLOAD_MB
    Per-request body size cap in megabytes. Requests exceeding this are
    rejected with HTTP 413 before the engine touches them. Default: 100.

FORWARDED_ALLOW_IPS (deployment, read by uvicorn)
    Networks of reverse proxies whose X-Forwarded-For uvicorn may trust.
    MUST be set when running behind Caddy/nginx (e.g. "172.16.0.0/12" for
    the default Docker bridge range), otherwise every request appears to
    come from the proxy IP and all users share a single rate-limit bucket.
"""

from __future__ import annotations

import os

from fastapi import Request
from slowapi import Limiter

_DEFAULT_RATE = "20/minute"
_DEFAULT_MAX_MB = 100

RATE_LIMIT = os.getenv("TOOLBOX_RATE_LIMIT", _DEFAULT_RATE).strip()
MAX_UPLOAD_MB = int(os.getenv("TOOLBOX_MAX_UPLOAD_MB", str(_DEFAULT_MAX_MB)))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024


def client_ip(request: Request) -> str:
    """Rate-limit key: the real client IP.

    uvicorn's ProxyHeadersMiddleware (on by default) rewrites
    ``request.client.host`` from X-Forwarded-For when the immediate peer is
    in FORWARDED_ALLOW_IPS — so behind a configured reverse proxy this is
    the end-user IP, and without a proxy it is the direct peer.

    Deliberately NOT slowapi's ``get_ipaddr``: it probes the misspelled
    header key ``X_FORWARDED_FOR`` (underscore), which never matches a
    Starlette header, and trusting a raw client-supplied X-Forwarded-For
    would let anyone rotate fake IPs to dodge the limit anyway.
    """
    return request.client.host if request.client else "127.0.0.1"


# Limiter is enabled either way; routes without `@limiter.limit(...)` are
# unaffected. Setting TOOLBOX_RATE_LIMIT="" disables limits on annotated routes
# because slowapi treats an empty string as "no limit".
limiter = Limiter(key_func=client_ip, headers_enabled=True)
