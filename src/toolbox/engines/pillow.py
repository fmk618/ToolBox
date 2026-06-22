"""Pillow image conversion engine.

Handles raster image format conversion: JPG, PNG, WebP, AVIF, TIFF, BMP,
GIF, ICO, and more. Pillow is a transitive dependency already present in the
venv (pulled in by docling/markitdown).

Transparent images (PNG, WebP, AVIF) that are converted to an opaque format
(JPG, BMP) have their alpha channel composited onto a white background.
"""

from pathlib import Path

from ..core.errors import ConversionFailedError
from .base import Engine

# Pillow save format names (second arg to Image.save()).
_FMT_TO_PIL: dict[str, str] = {
    "jpg":  "JPEG",
    "png":  "PNG",
    "webp": "WEBP",
    "avif": "AVIF",
    "tiff": "TIFF",
    "bmp":  "BMP",
    "gif":  "GIF",
    "ico":  "ICO",
}

# Formats that don't support an alpha channel.
_OPAQUE_FMTS = {"jpg", "bmp"}

_IMG_FMTS = list(_FMT_TO_PIL.keys())


class PillowEngine(Engine):
    name = "pillow"

    @property
    def available(self) -> bool:
        try:
            from PIL import Image  # noqa: F401
            return True
        except ImportError:
            return False

    def edges(self) -> list[tuple[str, str]]:
        pairs = []
        for src in _IMG_FMTS:
            for dst in _IMG_FMTS:
                if src != dst:
                    pairs.append((src, dst))
        return pairs

    def convert(self, src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
        from PIL import Image

        pil_fmt = _FMT_TO_PIL.get(dst_fmt)
        if pil_fmt is None:
            raise ConversionFailedError(
                f"pillow cannot emit '{dst_fmt}'"
            )

        try:
            img = Image.open(src)
        except Exception as e:
            raise ConversionFailedError(f"pillow: cannot open {src.name}: {e}") from e

        try:
            # Flatten alpha for formats that don't support it.
            if dst_fmt in _OPAQUE_FMTS and img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                img = bg
            elif pil_fmt == "JPEG" and img.mode != "RGB":
                img = img.convert("RGB")
            elif pil_fmt in ("PNG", "WEBP", "AVIF") and img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.getbands() else "RGB")

            save_kwargs: dict = {}
            if pil_fmt == "JPEG":
                save_kwargs["quality"] = 90
                save_kwargs["optimize"] = True
            elif pil_fmt == "WEBP":
                save_kwargs["quality"] = 88
                save_kwargs["method"] = 4
            elif pil_fmt == "PNG":
                save_kwargs["optimize"] = True

            img.save(dst, format=pil_fmt, **save_kwargs)
        except Exception as e:
            raise ConversionFailedError(
                f"pillow {src_fmt}→{dst_fmt}: {e}"
            ) from e
