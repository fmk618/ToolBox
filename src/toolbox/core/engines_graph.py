from collections import deque

from .errors import NoConversionPathError
from ..engines.base import Engine
from ..engines.docling import DoclingEngine
from ..engines.libreoffice import LibreOfficeEngine
from ..engines.markitdown import MarkItDownEngine
from ..engines.opendataloader import OpenDataLoaderEngine
from ..engines.pandoc import PandocEngine
from ..engines.pillow import PillowEngine
from ..engines.vision_llm import VisionLLMEngine

# Order matters: earlier engines win when multiple engines claim the same edge.
# For PDF→MD/HTML: VisionLLM > OpenDataLoader > Docling > MarkItDown.
# If the preferred engine fails at runtime, pipeline.convert() tries the next
# engine in the list for that hop (graceful fallback).
# Each engine is auto-skipped when its dependency is missing:
#   VisionLLM       ← provider + key configured in /settings/llm
#   OpenDataLoader  ← Java 11+ on PATH + opendataloader-pdf package
#   Docling / MarkItDown ← pure Python, always available after uv sync
ENGINES: list[Engine] = [
    VisionLLMEngine(),
    OpenDataLoaderEngine(),
    DoclingEngine(),
    MarkItDownEngine(),
    PandocEngine(),
    LibreOfficeEngine(),
    PillowEngine(),
]


def build_graph() -> dict[str, list[tuple[str, list[Engine]]]]:
    """Adjacency list: src_fmt → [(dst_fmt, [engines in priority order]), ...]

    All engines that handle the same (src, dst) pair are grouped together so
    that pipeline.convert() can fall back to the next engine when the
    preferred one fails at runtime.
    """
    edge_engines: dict[tuple[str, str], list[Engine]] = {}
    for engine in ENGINES:
        if not engine.available:
            continue
        for src, dst in engine.edges():
            edge_engines.setdefault((src, dst), []).append(engine)

    graph: dict[str, list[tuple[str, list[Engine]]]] = {}
    for (src, dst), engines in edge_engines.items():
        graph.setdefault(src, []).append((dst, engines))
    return graph


def find_path(src_fmt: str, dst_fmt: str) -> list[tuple[str, str, list[Engine]]]:
    """BFS for shortest conversion path.

    Returns a list of (from_fmt, to_fmt, engines) steps. Each step carries
    all engines capable of that hop in priority order so the pipeline can
    fall back automatically when the preferred engine fails.
    """
    if src_fmt == dst_fmt:
        return []

    graph = build_graph()
    if src_fmt not in graph:
        raise NoConversionPathError(
            f"No available engine can read format '{src_fmt}'"
        )

    queue: deque[tuple[str, list[tuple[str, str, list[Engine]]]]] = deque(
        [(src_fmt, [])]
    )
    visited = {src_fmt}
    while queue:
        node, path = queue.popleft()
        for nxt_fmt, engines in graph.get(node, []):
            if nxt_fmt in visited:
                continue
            new_path = path + [(node, nxt_fmt, engines)]
            if nxt_fmt == dst_fmt:
                return new_path
            visited.add(nxt_fmt)
            queue.append((nxt_fmt, new_path))

    raise NoConversionPathError(
        f"No conversion path from '{src_fmt}' to '{dst_fmt}'"
    )
