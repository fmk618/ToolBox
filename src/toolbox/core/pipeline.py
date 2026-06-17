import tempfile
from pathlib import Path

from .detect import detect_format
from ..router import find_path


def convert(src: Path, dst: Path, dst_fmt: str | None = None) -> list[str]:
    """Convert src → dst, returning the list of engine names that ran.

    Format is inferred from extensions unless dst_fmt is given explicitly.
    Multi-step paths are stored in a temp dir and cleaned up afterwards.
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
        for i, (from_fmt, to_fmt, engine) in enumerate(steps):
            is_last = i == len(steps) - 1
            step_out = dst if is_last else tmp_dir / f"step_{i}.{to_fmt}"
            step_out.parent.mkdir(parents=True, exist_ok=True)
            engine.convert(current, step_out, from_fmt, to_fmt)
            used.append(engine.name)
            current = step_out
    return used
