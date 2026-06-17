"""HTTP routes for the file-convert tool.

URL prefix is set when the router is mounted in `toolbox.api`
(`/tools/file-convert`). Endpoints here use plain paths so they read clearly
against the prefix.
"""

import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from ...core.engines_graph import ENGINES, build_graph
from ...core.errors import ToolboxError
from ...core.pipeline import convert

router = APIRouter(tags=["file-convert"])

_OUTPUT_DIR = Path(tempfile.gettempdir()) / "toolbox_out"
_OUTPUT_DIR.mkdir(exist_ok=True)


@router.get("/engines")
def list_engines():
    out = []
    for e in ENGINES:
        info = {"name": e.name, "available": e.available, "edges": e.edges()}
        if e.name == "vision-llm":
            try:
                pid, label, _base, model = e.active_config()  # type: ignore[attr-defined]
                info["active_provider"] = {"id": pid, "label": label, "model": model}
            except Exception:
                info["active_provider"] = None
        out.append(info)
    return out


@router.get("/routes")
def list_routes():
    graph = build_graph()
    return {
        src: [{"to": dst, "engine": eng.name} for dst, eng in nbrs]
        for src, nbrs in graph.items()
    }


@router.post("/convert")
def convert_endpoint(
    file: UploadFile = File(...),
    to: str = Query(..., description="Target format, e.g. 'md', 'pdf', 'docx'"),
):
    # sync def on purpose — convert() does long-running blocking I/O.
    # FastAPI runs sync routes in a thread pool, so they don't stall the
    # event loop and block /health, etc.
    if not file.filename:
        raise HTTPException(400, "filename required")

    job_id = uuid.uuid4().hex[:12]
    work_dir = _OUTPUT_DIR / job_id
    work_dir.mkdir(parents=True, exist_ok=True)

    src_path = work_dir / file.filename
    with src_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    dst_name = f"{src_path.stem}.{to}"
    dst_path = work_dir / dst_name
    try:
        convert(src_path, dst_path, dst_fmt=to)
    except ToolboxError as e:
        raise HTTPException(400, f"{type(e).__name__}: {e}")

    return FileResponse(
        dst_path,
        filename=dst_name,
        media_type="application/octet-stream",
    )
