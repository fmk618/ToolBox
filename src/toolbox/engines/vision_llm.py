"""Generic Vision-LLM PDF → Markdown engine.

Provider, model, and API key come from ``llm_settings`` (configured via the
UI Settings page). Renders each PDF page with ``pypdfium2``, posts to the
selected provider's OpenAI-compatible chat-completions endpoint, then
concatenates per-page Markdown.
"""

import base64
import io
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from ..core import llm_settings
from ..core.errors import ConversionFailedError, EngineNotAvailableError
from ..core.providers import get_provider
from .base import Engine

log = logging.getLogger("toolbox.vision_llm")

MAX_PARALLEL_PAGES = 4
PAGE_DPI_SCALE = 2.0  # ≈144 DPI, balance of quality vs upload size

PAGE_SEPARATORS = {
    "md": "\n\n---\n\n",
    "html": '\n\n<hr class="page-break"/>\n\n',
}

MD_PROMPT = """你是一个高保真 PDF→Markdown 转换器。我会给你 PDF 中一页的图片，你的任务：

1. **完整提取所有可见文字** —— 包括标题、正文、表格、列表、页眉页脚、页码、脚注、批注。一字不漏。
2. **不要改写、不要总结、不要翻译** —— 保持原始措辞、术语、缩写、标点不变。
3. **结构化 Markdown 输出**：
   - 标题用 `#` `##` `###`，层级与原页字号关系对应
   - 表格用 GFM 表格语法 `| 列1 | 列2 |`，**保留单元格合并/对齐**（用空单元格表达）
   - 有序列表用 `1.` `2.`，无序列表用 `-`
   - 加粗用 `**text**`，斜体用 `*text*`
   - 公式用 `$...$`（行内）或 `$$...$$`（独立行）
   - 代码/等宽用 ` ``` `
4. 图片/图表用 `![](placeholder) <!-- 描述：xxx -->` 占位，描述用一句话概括内容
5. 页眉页脚用 `> 页眉文本` 引用块单独成行；页码作为最后一行 `<!-- 页码: N -->`
6. **不要输出任何"以下是""这一页内容""根据图片"等额外文字、解释、思考过程**

**只输出 Markdown 原文本身**，不要 ```markdown 代码块包裹，不要前言后语。
"""

HTML_PROMPT = """你是一个高保真 PDF→HTML 转换器。我会给你 PDF 中一页的图片，你的任务：

1. **完整提取所有可见文字** —— 包括标题、正文、表格、列表、页眉页脚、页码、脚注。一字不漏。
2. **不要改写、不要总结、不要翻译** —— 保持原始措辞、术语、缩写、标点不变。
3. **输出语义化 HTML 片段**（不要 `<html>` `<head>` `<body>` 外壳，只输出 body 内的内容）：
   - 标题：`<h1>` ~ `<h6>`，层级与字号对应
   - 段落：`<p>`
   - 表格：`<table><thead>...<tbody><tr><td colspan="N" rowspan="N">...</td></tr></tbody></table>`，**必须保留合并单元格的 colspan / rowspan**
   - 列表：`<ul><li>`、`<ol><li>`
   - 加粗 `<strong>`、斜体 `<em>`、下划线 `<u>`、上下标 `<sup>` `<sub>`
   - 代码 `<code>`，预格式化 `<pre>`
   - 图片用 `<img alt="描述：xxx" src="placeholder"/>` 占位，alt 用一句话概括内容
4. 页眉页脚用 `<blockquote class="header">页眉文本</blockquote>`；页码用 `<p class="page-number">N</p>`
5. **不要输出任何"以下是""这一页内容""根据图片"等额外文字、解释、思考过程**

**只输出 HTML 内容本身**，不要 ``` 代码块包裹，不要前言后语，不要 `<!DOCTYPE>`。
"""


def _strip_markdown_fence(text: str) -> str:
    """Some models wrap responses in ```markdown ... ```; strip if present."""
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.split("\n")
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


class VisionLLMEngine(Engine):
    name = "vision-llm"

    @property
    def available(self) -> bool:
        s = llm_settings.load()
        return bool(s.get("provider") and s.get("api_key") and s.get("model"))

    def edges(self) -> list[tuple[str, str]]:
        # Order matters: BFS picks the first match. We put HTML before MD so
        # that multi-hop routes to richer targets (DOCX, EPUB) prefer the
        # HTML intermediate, which preserves tables/images/styling better
        # than Markdown when piped through pandoc.
        return [
            ("pdf", "html"),
            ("pdf", "md"),
        ]

    def active_config(self) -> tuple[str, str, str, str]:
        """Return (provider_id, provider_label, base_url, model).

        Raises EngineNotAvailableError if anything is missing.
        """
        s = llm_settings.load()
        provider_id = s.get("provider")
        api_key = s.get("api_key")
        model = s.get("model")
        if not (provider_id and api_key and model):
            raise EngineNotAvailableError(
                "Vision LLM not configured. Open the Settings page and pick a provider + model + API key."
            )
        spec = get_provider(provider_id)
        if spec is None:
            raise EngineNotAvailableError(f"Unknown provider '{provider_id}'")
        return provider_id, spec["label"], spec["base_url"], model

    def convert(self, src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
        provider_id, label, base_url, model = self.active_config()
        api_key = llm_settings.load()["api_key"]

        if dst_fmt == "html":
            system_prompt = HTML_PROMPT
            separator = PAGE_SEPARATORS["html"]
        elif dst_fmt == "md":
            system_prompt = MD_PROMPT
            separator = PAGE_SEPARATORS["md"]
        else:
            raise ConversionFailedError(
                f"vision-llm cannot output '{dst_fmt}' directly (only md/html)"
            )

        try:
            import pypdfium2 as pdfium
        except ImportError as e:
            raise ConversionFailedError(
                "pypdfium2 not installed (uv add pypdfium2)"
            ) from e

        pdf = pdfium.PdfDocument(str(src))
        page_count = len(pdf)
        log.info(
            f"Vision-LLM: {page_count} pages → {dst_fmt}, "
            f"provider={provider_id}, model={model}"
        )

        # 1) Render every page to PNG bytes in memory.
        page_pngs: list[bytes] = []
        try:
            for i in range(page_count):
                page = pdf[i]
                bitmap = page.render(scale=PAGE_DPI_SCALE)
                pil = bitmap.to_pil()
                buf = io.BytesIO()
                pil.save(buf, format="PNG", optimize=True)
                page_pngs.append(buf.getvalue())
        finally:
            pdf.close()

        # 2) Call the provider for every page in parallel (capped).
        def call_one(idx: int) -> tuple[int, str]:
            b64 = base64.b64encode(page_pngs[idx]).decode()
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{b64}"
                                },
                            }
                        ],
                    },
                ],
                "temperature": 0.0,
                "max_tokens": 4096,
            }
            with httpx.Client(timeout=180) as client:
                resp = client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            if resp.status_code != 200:
                raise ConversionFailedError(
                    f"{label} API HTTP {resp.status_code} on page {idx + 1}: "
                    f"{resp.text[:400]}"
                )
            data = resp.json()
            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError) as e:
                raise ConversionFailedError(
                    f"unexpected response from {label} on page {idx + 1}: {data!r}"
                ) from e
            return idx, _strip_markdown_fence(content)

        results: dict[int, str] = {}
        with ThreadPoolExecutor(
            max_workers=min(MAX_PARALLEL_PAGES, page_count)
        ) as pool:
            futures = [pool.submit(call_one, i) for i in range(page_count)]
            for fut in as_completed(futures):
                idx, content = fut.result()
                results[idx] = content
                log.info(f"Vision-LLM: page {idx + 1}/{page_count} done")

        # 3) Concatenate in original page order.
        ordered = [results[i] for i in range(page_count)]
        dst.write_text(separator.join(ordered), encoding="utf-8")


def test_provider_credentials(
    provider_id: str, model: str, api_key: str, timeout: float = 15.0
) -> tuple[bool, str]:
    """Ping the provider with a trivial request to verify the key works.

    Returns (ok, message). No image is sent — just a text-only call so it's
    fast and cheap.
    """
    spec = get_provider(provider_id)
    if spec is None:
        return False, f"未知 provider: {provider_id}"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                f"{spec['base_url'].rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 4,
                    "temperature": 0.0,
                },
            )
    except httpx.HTTPError as e:
        return False, f"网络错误: {e}"
    if resp.status_code == 200:
        return True, "连接成功"
    return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
