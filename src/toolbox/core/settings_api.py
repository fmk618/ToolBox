"""HTTP routes for global settings (LLM provider, API keys).

Mounted without prefix so endpoints sit at their absolute paths
(`/settings/llm`, `/providers`). LLM config is global, not per-tool — any
future tool that needs an LLM consumes from here.

Write operations (POST/DELETE) require Authorization: Bearer <TOOLBOX_ADMIN_TOKEN>.
GET /providers and GET /settings/llm remain public (no secrets exposed).
"""

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from . import llm_settings
from .providers import get_provider, list_providers
from ..engines.vision_llm import test_provider_credentials

router = APIRouter(tags=["settings"])

_ADMIN_TOKEN = os.getenv("TOOLBOX_ADMIN_TOKEN", "").strip()


def _require_admin(request: Request) -> None:
    if not _ADMIN_TOKEN:
        raise HTTPException(503, "TOOLBOX_ADMIN_TOKEN not configured on server")
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != _ADMIN_TOKEN:
        raise HTTPException(401, "invalid or missing admin token")


class LLMSettingsBody(BaseModel):
    provider: str
    model: str
    api_key: str


@router.get("/providers")
def providers_endpoint():
    """List supported Vision-LLM providers (catalog, no keys)."""
    return list_providers()


@router.get("/settings/llm")
def get_llm_settings():
    """Current Vision-LLM config; API key is masked."""
    return llm_settings.public_view(llm_settings.load())


@router.post("/settings/llm")
def save_llm_settings(body: LLMSettingsBody, _: None = Depends(_require_admin)):
    spec = get_provider(body.provider)
    if spec is None:
        raise HTTPException(400, f"unknown provider: {body.provider}")
    if not body.model.strip():
        raise HTTPException(400, "model is required")
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


@router.delete("/settings/llm")
def clear_llm_settings(_: None = Depends(_require_admin)):
    llm_settings.clear()
    return {"cleared": True}


@router.post("/settings/llm/test")
def test_llm_settings(body: LLMSettingsBody, _: None = Depends(_require_admin)):
    """Ping the provider with a trivial text-only request — fast + cheap."""
    ok, message = test_provider_credentials(body.provider, body.model, body.api_key)
    return {"ok": ok, "message": message}
