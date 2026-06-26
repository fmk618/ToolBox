"""Catalog of supported Vision-LLM providers.

Each provider has an OpenAI-compatible chat-completions endpoint. The runtime
``VisionLLMEngine`` picks one from this catalog based on the user's saved
settings in ``~/.toolbox/llm.json``.

The ``models`` list is a set of known defaults; the frontend allows free-text
input so users can specify any model the provider offers without requiring a
code update.
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
    "openai": {
        "id": "openai",
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": [
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4o",
            "gpt-4o-mini",
            "o4-mini",
            "o3",
        ],
        "default_model": "gpt-4o",
        "api_docs": "https://platform.openai.com/api-keys",
        "description": "GPT-4o / GPT-4.1 视觉模型，支持高分辨率图像，识别质量高。",
    },
    "deepseek": {
        "id": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "models": [
            "deepseek-chat",
            "deepseek-reasoner",
        ],
        "default_model": "deepseek-chat",
        "api_docs": "https://platform.deepseek.com/api_keys",
        "description": "DeepSeek-V3 / R1，性价比极高、中文友好。注：视觉能力有限，适合文字类 PDF。",
    },
    "qwen": {
        "id": "qwen",
        "label": "通义千问 (阿里百炼)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": [
            "qwen2.5-vl-72b-instruct",
            "qwen2.5-vl-7b-instruct",
            "qwen-vl-max",
            "qwen-vl-plus",
            "qwen-vl-ocr",
        ],
        "default_model": "qwen2.5-vl-72b-instruct",
        "api_docs": "https://bailian.console.aliyun.com/",
        "description": "通义千问 VL 系列，中文 PDF 表格识别业界顶尖。qwen-vl-ocr 专为 OCR 场景优化。",
    },
    "gemini": {
        "id": "gemini",
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "models": [
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-1.5-pro",
            "gemini-1.5-flash",
        ],
        "default_model": "gemini-2.5-flash",
        "api_docs": "https://aistudio.google.com/apikey",
        "description": "Google Gemini，长上下文、超大图像输入，免费额度慷慨。",
    },
    "zhipu": {
        "id": "zhipu",
        "label": "智谱 AI (GLM)",
        "base_url": "https://open.bigmodel.cn/api/paas/v4/",
        "models": [
            "glm-4v-plus",
            "glm-4v",
        ],
        "default_model": "glm-4v-plus",
        "api_docs": "https://bigmodel.cn/usercenter/apikeys",
        "description": "智谱 GLM-4V，国内访问稳定，中文理解优秀，有免费额度。",
    },
}


def get_provider(provider_id: str) -> ProviderSpec | None:
    return PROVIDERS.get(provider_id)


def list_providers() -> list[ProviderSpec]:
    return list(PROVIDERS.values())
