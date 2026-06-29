import shutil
import subprocess
from pathlib import Path

from ..core.errors import ConversionFailedError
from .base import Engine


class PandocEngine(Engine):
    name = "pandoc"

    @property
    def available(self) -> bool:
        return shutil.which("pandoc") is not None

    def edges(self) -> list[tuple[str, str]]:
        # NOTE: no direct ("md", "pdf") edge on purpose. Pandoc's only PDF path
        # is via a LaTeX engine (xelatex), which silently drops every CJK glyph
        # unless a CJK font is wired up and a full TeX install is present —
        # neither holds in the slim Docker image. All →pdf conversions in this
        # project go through LibreOffice instead (md→docx here, docx→pdf there),
        # which renders CJK / symbols / task-list checkboxes correctly.
        return [
            ("md", "docx"),
            ("md", "html"),
            ("md", "epub"),
            ("md", "rtf"),
            ("md", "odt"),
            ("docx", "md"),
            ("docx", "html"),
            ("html", "md"),
            ("html", "docx"),
            ("epub", "md"),
            ("rtf", "md"),
            ("odt", "md"),
        ]

    def convert(self, src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
        cmd = ["pandoc", str(src), "-o", str(dst)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise ConversionFailedError(
                f"pandoc {src_fmt}→{dst_fmt}: {proc.stderr.strip() or 'unknown error'}"
            )
