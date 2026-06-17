from pathlib import Path

from ..core.errors import ConversionFailedError
from .base import Engine


class DoclingEngine(Engine):
    """IBM Docling — ML-based layout analysis. High-quality PDF → MD with
    table/heading/list detection. ~500MB install (PyTorch + models); first
    conversion downloads ~200MB of model weights into cache.
    """

    name = "docling"

    # Cache the heavy DocumentConverter across calls so model load happens once.
    _converter = None

    @property
    def available(self) -> bool:
        try:
            import docling  # noqa: F401

            return True
        except ImportError:
            return False

    def edges(self) -> list[tuple[str, str]]:
        # Only claim what Docling actually does better than markitdown.
        # PDF is the killer use case; for other formats markitdown is faster
        # and quality difference is negligible.
        return [
            ("pdf", "md"),
        ]

    def _get_converter(self):
        if DoclingEngine._converter is None:
            from docling.document_converter import DocumentConverter

            DoclingEngine._converter = DocumentConverter()
        return DoclingEngine._converter

    def convert(self, src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
        try:
            converter = self._get_converter()
            result = converter.convert(str(src))
            md = result.document.export_to_markdown()
        except Exception as e:
            raise ConversionFailedError(f"docling {src_fmt}→{dst_fmt}: {e}") from e
        dst.write_text(md, encoding="utf-8")
