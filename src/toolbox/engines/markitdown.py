from pathlib import Path

from ..core.errors import ConversionFailedError
from .base import Engine


class MarkItDownEngine(Engine):
    name = "markitdown"

    @property
    def available(self) -> bool:
        try:
            import markitdown  # noqa: F401

            return True
        except ImportError:
            return False

    def edges(self) -> list[tuple[str, str]]:
        return [
            ("pdf", "md"),
            ("docx", "md"),
            ("pptx", "md"),
            ("xlsx", "md"),
            ("html", "md"),
            ("epub", "md"),
            ("csv", "md"),
            ("json", "md"),
            ("txt", "md"),
        ]

    def convert(self, src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
        from markitdown import MarkItDown

        md = MarkItDown()
        try:
            result = md.convert(str(src))
        except Exception as e:
            raise ConversionFailedError(f"markitdown: {e}") from e
        dst.write_text(result.text_content or "", encoding="utf-8")
