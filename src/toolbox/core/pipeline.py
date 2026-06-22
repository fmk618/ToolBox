import logging
import tempfile
from pathlib import Path

from .detect import detect_format
from .engines_graph import find_path
from .errors import ConversionFailedError

log = logging.getLogger("toolbox.pipeline")


def convert(src: Path, dst: Path, dst_fmt: str | None = None) -> list[str]:
    """Convert src → dst, returning the list of engine names that ran.

    Format is inferred from extensions unless dst_fmt is given explicitly.
    Multi-step paths are stored in a temp dir and cleaned up afterwards.

    For each step, engines are tried in priority order. If the preferred
    engine raises ConversionFailedError, the next engine for that hop is
    tried automatically (with a warning log). The step fails only when all
    engines for that hop are exhausted.
    """
    src_fmt = detect_format(src)
    if dst_fmt is None:
        dst_fmt = detect_format(dst)

    steps = find_path(src_fmt, dst_fmt)
    if not steps:
        dst.write_bytes(src.read_bytes())
        return []

    used: list[str] = []
    current = src
    with tempfile.TemporaryDirectory(prefix="toolbox_") as tmp:
        tmp_dir = Path(tmp)
        for i, (from_fmt, to_fmt, engines) in enumerate(steps):
            is_last = i == len(steps) - 1
            step_out = dst if is_last else tmp_dir / f"step_{i}.{to_fmt}"
            step_out.parent.mkdir(parents=True, exist_ok=True)

            last_err: ConversionFailedError | None = None
            for engine in engines:
                try:
                    engine.convert(current, step_out, from_fmt, to_fmt)
                    used.append(engine.name)
                    last_err = None
                    break
                except ConversionFailedError as e:
                    last_err = e
                    if len(engines) > 1:
                        log.warning(
                            "engine %s failed %s→%s: %s; trying next engine",
                            engine.name, from_fmt, to_fmt, e,
                        )
            if last_err is not None:
                raise last_err

            current = step_out
    return used
