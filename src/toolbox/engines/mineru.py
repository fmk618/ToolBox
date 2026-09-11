"""Optional local MinerU CLI engine for complex documents."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..core.errors import ConversionFailedError
from .base import Engine

_SUPPORTED_INPUTS = (
    "pdf",
    "docx",
    "pptx",
    "xlsx",
    "jpg",
    "png",
    "webp",
    "avif",
    "tiff",
    "bmp",
)
_MAX_OUTPUT_BYTES = 20 * 1024 * 1024
_TIMEOUT_SECONDS = 600


class MinerUEngine(Engine):
    name = "mineru"

    @staticmethod
    def _binary() -> str:
        return os.getenv("TOOLBOX_MINERU_BIN", "mineru").strip() or "mineru"

    @property
    def available(self) -> bool:
        return shutil.which(self._binary()) is not None

    def edges(self) -> list[tuple[str, str]]:
        return [(source, "md") for source in _SUPPORTED_INPUTS]

    @staticmethod
    def _markdown_output(root: Path, source: Path) -> Path | None:
        try:
            root_resolved = root.resolve(strict=True)
        except OSError:
            return None
        candidates: list[Path] = []
        for candidate in sorted(root.rglob("*.md")):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(root_resolved)
            except (OSError, ValueError):
                continue
            candidates.append(candidate)
        if not candidates:
            return None
        preferred = [item for item in candidates if item.stem == source.stem]
        return (preferred or candidates)[0]

    def convert(self, src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
        if src_fmt not in _SUPPORTED_INPUTS or dst_fmt != "md":
            raise ConversionFailedError("mineru only outputs Markdown for supported complex documents")
        with tempfile.TemporaryDirectory(prefix="toolbox_mineru_") as output_dir:
            output_root = Path(output_dir)
            command = [
                self._binary(),
                "-p",
                str(src),
                "-o",
                str(output_root),
                "-b",
                "pipeline",
            ]
            try:
                result = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=_TIMEOUT_SECONDS,
                )
            except FileNotFoundError as exc:
                raise ConversionFailedError("MinerU is not installed or unavailable") from exc
            except OSError as exc:
                raise ConversionFailedError("MinerU could not be started") from exc
            except subprocess.TimeoutExpired as exc:
                raise ConversionFailedError("MinerU timed out while parsing the document") from exc
            if result.returncode != 0:
                raise ConversionFailedError(
                    f"MinerU failed with exit code {result.returncode}"
                )
            markdown = self._markdown_output(output_root, src)
            if markdown is None:
                raise ConversionFailedError("MinerU did not produce a Markdown result")
            try:
                if markdown.stat().st_size > _MAX_OUTPUT_BYTES:
                    raise ConversionFailedError("MinerU Markdown output is too large")
                content = markdown.read_text(encoding="utf-8")
            except OSError as exc:
                raise ConversionFailedError("MinerU Markdown result could not be read") from exc
            dst.write_text(content, encoding="utf-8")
