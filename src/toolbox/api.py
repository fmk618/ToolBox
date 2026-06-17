import logging
import shutil
import tempfile
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .core import llm_settings
from .core.errors import ToolboxError
from .core.pipeline import convert
from .core.providers import get_provider, list_providers
from .engines.vision_llm import test_provider_credentials
from .router import ENGINES, build_graph

log = logging.getLogger("toolbox.api")


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
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

_OUTPUT_DIR = Path(tempfile.gettempdir()) / "toolbox_out"
_OUTPUT_DIR.mkdir(exist_ok=True)


# ---------------------------- basic ----------------------------

@api.get("/health")
def health():
    return {"status": "ok"}


@api.get("/engines")
def list_engines():
    out = []
    for e in ENGINES:
        info = {"name": e.name, "available": e.available, "edges": e.edges()}
        if e.name == "vision-llm":
            try:
                pid, label, _base, model = e.active_config()  # type: ignore[attr-defined]
                info["active_provider"] = {"id": pid, "label": label, "model": model}
            except Exception:
                info["active_provider"] = None
        out.append(info)
    return out


@api.get("/routes")
def list_routes():
    graph = build_graph()
    return {
        src: [{"to": dst, "engine": eng.name} for dst, eng in nbrs]
        for src, nbrs in graph.items()
    }


# --------------------------- providers --------------------------

@api.get("/providers")
def providers_endpoint():
    """List supported Vision-LLM providers (catalog, no keys)."""
    return list_providers()


# ------------------------- LLM settings -------------------------

class LLMSettingsBody(BaseModel):
    provider: str
    model: str
    api_key: str


@api.get("/settings/llm")
def get_llm_settings():
    """Current Vision-LLM config; API key is masked."""
    return llm_settings.public_view(llm_settings.load())


@api.post("/settings/llm")
def save_llm_settings(body: LLMSettingsBody):
    spec = get_provider(body.provider)
    if spec is None:
        raise HTTPException(400, f"unknown provider: {body.provider}")
    if body.model not in spec["models"]:
        raise HTTPException(
            400, f"model '{body.model}' not supported by '{body.provider}'"
        )
    if not body.api_key.strip():
        raise HTTPException(400, "api_key is required")
    llm_settings.save(
        {
            "provider": body.provider,
            "model": body.model,
            "api_key": body.api_key.strip(),
        }
    )
    return llm_settings.public_view(llm_settings.load())


@api.delete("/settings/llm")
def clear_llm_settings():
    llm_settings.clear()
    return {"cleared": True}


@api.post("/settings/llm/test")
def test_llm_settings(body: LLMSettingsBody):
    """Ping the provider with a trivial text-only request — fast + cheap."""
    ok, message = test_provider_credentials(body.provider, body.model, body.api_key)
    return {"ok": ok, "message": message}


# ---------------------------- convert ---------------------------

@api.post("/convert")
def convert_endpoint(
    file: UploadFile = File(...),
    to: str = Query(..., description="Target format, e.g. 'md', 'pdf', 'docx'"),
):
    # NOTE: sync def on purpose — `convert()` does long-running blocking I/O
    # (subprocess calls, HTTP calls to LLM). FastAPI runs sync routes in a
    # thread pool so they don't stall the event loop and block /health, etc.
    if not file.filename:
        raise HTTPException(400, "filename required")

    job_id = uuid.uuid4().hex[:12]
    work_dir = _OUTPUT_DIR / job_id
    work_dir.mkdir(parents=True, exist_ok=True)

    src_path = work_dir / file.filename
    with src_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    dst_name = f"{src_path.stem}.{to}"
    dst_path = work_dir / dst_name
    try:
        convert(src_path, dst_path, dst_fmt=to)
    except ToolboxError as e:
        raise HTTPException(400, f"{type(e).__name__}: {e}")

    return FileResponse(
        dst_path,
        filename=dst_name,
        media_type="application/octet-stream",
    )
