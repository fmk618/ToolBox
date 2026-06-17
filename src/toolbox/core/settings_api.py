"""HTTP routes for global settings (LLM provider, API keys).

Mounted without prefix so endpoints sit at their absolute paths
(`/settings/llm`, `/providers`). LLM config is global, not per-tool — any
future tool that needs an LLM consumes from here.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import llm_settings
from .providers import get_provider, list_providers
from ..engines.vision_llm import test_provider_credentials

router = APIRouter(tags=["settings"])


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


@router.delete("/settings/llm")
def clear_llm_settings():
    llm_settings.clear()
    return {"cleared": True}


@router.post("/settings/llm/test")
def test_llm_settings(body: LLMSettingsBody):
    """Ping the provider with a trivial text-only request — fast + cheap."""
    ok, message = test_provider_credentials(body.provider, body.model, body.api_key)
    return {"ok": ok, "message": message}
