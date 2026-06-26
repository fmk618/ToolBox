"""HTTP routes for global settings.

LLM credentials are now user-owned and sent per-request from the browser —
this module only serves the provider catalog and a key-test helper.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .providers import get_provider, list_providers
from ..engines.vision_llm import test_provider_credentials

router = APIRouter(tags=["settings"])


class LLMTestBody(BaseModel):
    provider: str
    model: str
    api_key: str


@router.get("/providers")
def providers_endpoint():
    """List supported Vision-LLM providers (catalog only, no keys)."""
    return list_providers()


@router.post("/settings/llm/test")
def test_llm_settings(body: LLMTestBody):
    """Ping the provider with a trivial request to verify the key works."""
    spec = get_provider(body.provider)
    if spec is None:
        raise HTTPException(400, f"unknown provider: {body.provider}")
    if not body.model.strip():
        raise HTTPException(400, "model is required")
    ok, message = test_provider_credentials(body.provider, body.model, body.api_key)
    return {"ok": ok, "message": message}
