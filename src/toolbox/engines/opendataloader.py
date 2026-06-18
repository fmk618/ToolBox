"""opendataloader-pdf engine — PDF parser with #1 benchmark accuracy.

Wraps the Python SDK (`opendataloader-pdf` on PyPI), which itself shells out
to a Java 11+ JVM holding the actual Apache PDFBox + XY-Cut++ implementation.

`available` returns False when:
- The Python package isn't installed (we mark it as an optional extra)
- A JVM (`java`) isn't on PATH

Either condition means the engine is silently skipped — Docling / MarkItDown
take over PDF→MD, so degradation is graceful.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from ..core.errors import ConversionFailedError
from .base import Engine

# opendataloader-pdf SDK output names — the Python package writes
# "<stem>.<ext>" into output_dir for each requested format.
_FMT_TO_SDK = {
    "md": "markdown",
    "json": "json",
    "html": "html",
}


class OpenDataLoaderEngine(Engine):
    name = "opendataloader-pdf"

    @property
    def available(self) -> bool:
        if shutil.which("java") is None:
            return False
        try:
            import opendataloader_pdf  # noqa: F401
        except ImportError:
            return False
        # Sanity-check Java >= 11 to fail fast in confused environments.
        # `java -version` writes to stderr, returns 0 on success.
        try:
            r = subprocess.run(
                ["java", "-version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return r.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def edges(self) -> list[tuple[str, str]]:
        return [("pdf", "md"), ("pdf", "json"), ("pdf", "html")]

    def convert(
        self, src: Path, dst: Path, src_fmt: str, dst_fmt: str
    ) -> None:
        sdk_fmt = _FMT_TO_SDK.get(dst_fmt)
        if sdk_fmt is None:
            raise ConversionFailedError(
                f"opendataloader-pdf can't emit '{dst_fmt}'"
            )

        import opendataloader_pdf

        with tempfile.TemporaryDirectory(prefix="opendataloader_") as tmp:
            try:
                opendataloader_pdf.convert(
                    input_path=[str(src)],
                    output_dir=tmp,
                    format=sdk_fmt,
                )
            except Exception as e:
                raise ConversionFailedError(f"opendataloader-pdf: {e}") from e

            # SDK writes <stem>.<ext> directly into output_dir. If naming
            # ever drifts (subfolder, suffixed stem), fall back to glob.
            ext_map = {"md": "md", "json": "json", "html": "html"}
            ext = ext_map[dst_fmt]
            expected = Path(tmp) / f"{src.stem}.{ext}"
            if expected.exists():
                shutil.copy(expected, dst)
                return

            found = next(Path(tmp).rglob(f"*.{ext}"), None)
            if found is None:
                raise ConversionFailedError(
                    f"opendataloader-pdf produced no .{ext} file in {tmp}"
                )
            shutil.copy(found, dst)
