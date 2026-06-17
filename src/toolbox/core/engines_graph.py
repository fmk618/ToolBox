from collections import deque

from .errors import NoConversionPathError
from ..engines.base import Engine
from ..engines.docling import DoclingEngine
from ..engines.libreoffice import LibreOfficeEngine
from ..engines.markitdown import MarkItDownEngine
from ..engines.pandoc import PandocEngine
from ..engines.vision_llm import VisionLLMEngine

# Order matters: earlier engines win when multiple engines claim the same edge.
# Vision LLM > Docling > MarkItDown for PDF→MD
# (cloud vision model > local ML layout > raw text extraction).
# VisionLLMEngine is auto-skipped when no provider/key is configured.
ENGINES: list[Engine] = [
    VisionLLMEngine(),
    DoclingEngine(),
    MarkItDownEngine(),
    PandocEngine(),
    LibreOfficeEngine(),
]


def build_graph() -> dict[str, list[tuple[str, Engine]]]:
    """Adjacency list: src_fmt → [(dst_fmt, engine), ...] over AVAILABLE engines.

    Engines registered earlier in ENGINES take precedence in BFS ordering.
    """
    graph: dict[str, list[tuple[str, Engine]]] = {}
    for engine in ENGINES:
        if not engine.available:
            continue
        for src, dst in engine.edges():
            graph.setdefault(src, []).append((dst, engine))
    return graph


def find_path(src_fmt: str, dst_fmt: str) -> list[tuple[str, str, Engine]]:
    """BFS for shortest conversion path. Returns list of (from, to, engine) steps."""
    if src_fmt == dst_fmt:
        return []

    graph = build_graph()
    if src_fmt not in graph:
        raise NoConversionPathError(
            f"No available engine can read format '{src_fmt}'"
        )

    queue: deque[tuple[str, list[tuple[str, str, Engine]]]] = deque(
        [(src_fmt, [])]
    )
    visited = {src_fmt}
    while queue:
        node, path = queue.popleft()
        for nxt_fmt, engine in graph.get(node, []):
            if nxt_fmt in visited:
                continue
            new_path = path + [(node, nxt_fmt, engine)]
            if nxt_fmt == dst_fmt:
                return new_path
            visited.add(nxt_fmt)
            queue.append((nxt_fmt, new_path))

    raise NoConversionPathError(
        f"No conversion path from '{src_fmt}' to '{dst_fmt}'"
    )
