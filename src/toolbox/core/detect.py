from pathlib import Path

from .errors import UnknownFormatError

EXTENSION_MAP: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "doc",
    ".md": "md",
    ".markdown": "md",
    ".html": "html",
    ".htm": "html",
    ".pptx": "pptx",
    ".ppt": "ppt",
    ".xlsx": "xlsx",
    ".xls": "xls",
    ".epub": "epub",
    ".txt": "txt",
    ".rtf": "rtf",
    ".odt": "odt",
    ".csv": "csv",
    ".json": "json",
}


def detect_format(path: Path) -> str:
    ext = path.suffix.lower()
    fmt = EXTENSION_MAP.get(ext)
    if fmt is None:
        raise UnknownFormatError(
            f"Cannot detect format from extension: {ext or '(none)'} (path={path})"
        )
    return fmt
