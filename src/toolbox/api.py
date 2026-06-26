"""Toolbox HTTP API — thin app shell.

Each tool registers its own APIRouter under `tools/<slug>/router.py` and is
mounted here under `/tools/<slug>`. Global concerns (CORS, health, model
warmup, LLM settings, rate limits, upload size) live in this file or `core/`.
"""

import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from .core.limits import MAX_UPLOAD_BYTES, MAX_UPLOAD_MB, limiter
from .core.settings_api import router as settings_router
from .tools.file_convert import router as file_convert_router

log = logging.getLogger("toolbox.api")

# Comma-separated list of origins allowed to hit the API. Override in production
# via env to your real deploy domain(s) — defaults serve local dev.
_DEFAULT_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("TOOLBOX_ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",")
    if o.strip()
]


def _warmup_docling():
    """Eagerly load Docling's ML models so the first user conversion is fast."""
    try:
        from .engines.docling import DoclingEngine

        engine = DoclingEngine()
        if not engine.available:
            return
        log.info("Pre-warming Docling models (one-off, ~30s)...")
        engine._get_converter()
        log.info("Docling pre-warmed ✓")
    except Exception as e:
        log.warning(f"Docling pre-warm skipped: {e}")


_debug = os.getenv("TOOLBOX_DEBUG", "").strip() == "1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_warmup_docling, daemon=True).start()
    yield


api = FastAPI(
    title="Toolbox",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _debug else None,
    redoc_url="/redoc" if _debug else None,
    openapi_url="/openapi.json" if _debug else None,
)

# ---- Rate limiting (slowapi) ----
# Limits are decorated per-route in `tools/<slug>/router.py`. App-level wiring
# below registers the limiter & its 429 handler. Empty TOOLBOX_RATE_LIMIT
# disables enforcement on annotated routes.
api.state.limiter = limiter


@api.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        {"detail": f"rate limit exceeded: {exc.detail}"},
        status_code=429,
        headers={"Retry-After": "60"},
    )


# ---- Upload size cap (Content-Length precheck) ----
class UploadSizeLimiter(BaseHTTPMiddleware):
    """Reject POSTs hitting /tools/file-convert/convert whose Content-Length
    exceeds MAX_UPLOAD_BYTES. Streams without Content-Length pass through;
    the engine itself caps memory inside its temp file pipeline.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method == "POST" and path.endswith("/file-convert/convert"):
            cl = request.headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > MAX_UPLOAD_BYTES:
                return Response(
                    content=(
                        f'{{"detail":"file too large: max {MAX_UPLOAD_MB} MB"}}'
                    ).encode(),
                    status_code=413,
                    media_type="application/json",
                )
        return await call_next(request)


api.add_middleware(UploadSizeLimiter)

api.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


@api.get("/health")
def health():
    return {"status": "ok"}


api.include_router(settings_router)
api.include_router(file_convert_router, prefix="/tools/file-convert")
