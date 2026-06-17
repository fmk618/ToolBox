"""Catalog of supported Vision-LLM providers.

Each provider has an OpenAI-compatible chat-completions endpoint. The runtime
``VisionLLMEngine`` picks one from this catalog based on the user's saved
settings in ``~/.toolbox/llm.json``.
"""

from typing import TypedDict


class ProviderSpec(TypedDict):
    id: str
    label: str
    base_url: str
    models: list[str]
    default_model: str
    api_docs: str
    description: str


PROVIDERS: dict[str, ProviderSpec] = {
    "deepseek": {
        "id": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-v4-pro", "deepseek-v4-flash"],
        "default_model": "deepseek-v4-pro",
        "api_docs": "https://platform.deepseek.com/api_keys",
        "description": "DeepSeek V4 native multimodal，性价比高、中文友好。",
    },
    "qwen": {
        "id": "qwen",
        "label": "通义千问 (阿里百炼)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": [
            "qwen3-vl-plus",
            "qwen3-vl-flash",
            "qwen-vl-max",
            "qwen-vl-plus",
            "qwen-vl-ocr",
        ],
        "default_model": "qwen3-vl-plus",
        "api_docs": "https://bailian.console.aliyun.com/?tab=api#/api/?type=model&url=2840914",
        "description": "阿里通义千问 VL 系列，中文 PDF 表格识别业界顶尖。qwen-vl-ocr 专为 OCR 优化。",
    },
    "openai": {
        "id": "openai",
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini"],
        "default_model": "gpt-4o",
        "api_docs": "https://platform.openai.com/api-keys",
        "description": "GPT-4o vision，老牌稳定，价格中等。",
    },
}


def get_provider(provider_id: str) -> ProviderSpec | None:
    return PROVIDERS.get(provider_id)


def list_providers() -> list[ProviderSpec]:
    return list(PROVIDERS.values())
