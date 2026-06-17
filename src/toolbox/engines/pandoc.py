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
        return [
            ("md", "docx"),
            ("md", "html"),
            ("md", "pdf"),
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
        if dst_fmt == "pdf":
            cmd += ["--pdf-engine=xelatex"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise ConversionFailedError(
                f"pandoc {src_fmt}→{dst_fmt}: {proc.stderr.strip() or 'unknown error'}"
            )
