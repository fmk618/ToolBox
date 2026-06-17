import shutil
import subprocess
import tempfile
from pathlib import Path

from ..core.errors import ConversionFailedError, EngineNotAvailableError
from .base import Engine


class LibreOfficeEngine(Engine):
    name = "libreoffice"

    def _binary(self) -> str | None:
        return shutil.which("soffice") or shutil.which("libreoffice")

    @property
    def available(self) -> bool:
        return self._binary() is not None

    def edges(self) -> list[tuple[str, str]]:
        return [
            ("docx", "pdf"),
            ("doc", "pdf"),
            ("odt", "pdf"),
            ("pptx", "pdf"),
            ("ppt", "pdf"),
            ("xlsx", "pdf"),
            ("xls", "pdf"),
            ("rtf", "pdf"),
            ("html", "pdf"),
        ]

    def convert(self, src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
        binary = self._binary()
        if not binary:
            raise EngineNotAvailableError("libreoffice (soffice) not installed")

        dst.parent.mkdir(parents=True, exist_ok=True)
        # Write to an isolated temp dir to avoid LibreOffice's "<stem>.<ext>" naming
        # clobbering unrelated files (or the input itself) in dst.parent.
        with tempfile.TemporaryDirectory(prefix="soffice_") as staging:
            cmd = [
                binary,
                "--headless",
                "--norestore",
                "--convert-to",
                dst_fmt,
                "--outdir",
                staging,
                str(src),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if proc.returncode != 0:
                raise ConversionFailedError(
                    f"libreoffice {src_fmt}→{dst_fmt}: {proc.stderr.strip() or 'unknown error'}"
                )
            produced = Path(staging) / f"{src.stem}.{dst_fmt}"
            if not produced.exists():
                raise ConversionFailedError(
                    f"libreoffice produced no output at {produced}"
                )
            shutil.move(str(produced), str(dst))
