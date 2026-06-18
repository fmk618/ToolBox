"""Toolbox HTTP API — thin app shell.

Each tool registers its own APIRouter under `tools/<slug>/router.py` and is
mounted here under `/tools/<slug>`. Global concerns (CORS, health, model
warmup, LLM settings) live in this file or `core/`.
"""

import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_warmup_docling, daemon=True).start()
    yield


api = FastAPI(title="Toolbox", version="0.1.0", lifespan=lifespan)

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
