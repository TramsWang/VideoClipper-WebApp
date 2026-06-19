"""FastAPI entrypoint for VideoClipper Web App."""

from __future__ import annotations

import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.settings import settings
from app.task_runner import TaskRunner
from app.task_store import InvalidTaskIdError, TaskNotFoundError, TaskRecord, TaskStore


CHUNK_SIZE = 1024 * 1024


class UploadTooLargeError(ValueError):
    """Raised when an upload exceeds the configured maximum size."""


store = TaskStore(settings)
runner = TaskRunner(settings, store)
templates = Jinja2Templates(directory=str(settings.templates_dir))


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.ensure_initialized()
    runner.startup()
    try:
        yield
    finally:
        runner.shutdown()


app = FastAPI(title="VideoClipper Web App", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "max_upload_mb": settings.max_upload_mb,
            "allowed_extensions": sorted(settings.allowed_video_extensions),
        },
    )


@app.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(request: Request, task_id: str) -> HTMLResponse:
    record = _load_task_or_404(task_id)
    return templates.TemplateResponse(request, "task.html", {"task": record})


@app.post("/api/tasks")
async def create_task(file: UploadFile = File(...), language: str = Form(...)) -> dict[str, str]:
    if language not in {"zh", "en"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="language must be zh or en")

    original_filename = file.filename or "upload"
    extension = Path(original_filename).suffix.lower()
    if extension not in settings.allowed_video_extensions:
        allowed = ", ".join(sorted(settings.allowed_video_extensions))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"unsupported video extension: {allowed}")

    record = store.create_task(language=language, original_filename=original_filename, input_extension=extension)
    input_path = store.record_path(record, "input_path")
    try:
        await _save_upload_limited(file, input_path)
    except UploadTooLargeError as exc:
        store.cleanup(str(record["task_id"]))
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file must be no larger than {settings.max_upload_mb} MB",
        ) from exc
    except Exception:
        store.cleanup(str(record["task_id"]))
        raise

    runner.submit(str(record["task_id"]))
    return {
        "task_id": str(record["task_id"]),
        "detail_url": f"/tasks/{record['task_id']}",
    }


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str) -> dict[str, Any]:
    record = _load_task_or_404(task_id)
    return {
        "task_id": record["task_id"],
        "status": record["status"],
        "language": record["language"],
        "mode": record["mode"],
        "error": record["error"],
        "created_at": record["created_at"],
        "started_at": record["started_at"],
        "finished_at": record["finished_at"],
    }


@app.get("/api/tasks/{task_id}/log")
async def get_task_log(task_id: str, offset: int = 0) -> dict[str, Any]:
    if offset < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="offset must be non-negative")
    record = _load_task_or_404(task_id)
    log_path = store.record_path(record, "log_path")
    if not log_path.exists():
        return {"offset": 0, "content": ""}

    size = log_path.stat().st_size
    if offset > size:
        offset = 0
    with log_path.open("rb") as file:
        file.seek(offset)
        content = file.read()
        next_offset = file.tell()
    return {"offset": next_offset, "content": content.decode("utf-8", errors="replace")}


@app.get("/api/tasks/{task_id}/result")
async def get_task_result(task_id: str) -> dict[str, Any]:
    record = _load_task_or_404(task_id)
    if record["status"] != "succeeded":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="task is not completed")

    subtitle_path = _final_subtitle_path(record)
    if not subtitle_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subtitle file not found")

    clips_dir = store.record_path(record, "clips_dir")
    return {
        "task_id": task_id,
        "subtitle": {
            "path": f"/api/tasks/{task_id}/subtitle",
            "filename": subtitle_path.name,
            "rows": _parse_tsv_rows(subtitle_path),
        },
        "clips": _list_clips(task_id, clips_dir),
    }


@app.get("/api/tasks/{task_id}/subtitle")
async def get_task_subtitle(task_id: str) -> FileResponse:
    record = _load_task_or_404(task_id)
    if record["status"] != "succeeded":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="task is not completed")
    subtitle_path = _final_subtitle_path(record)
    if not subtitle_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subtitle file not found")
    return FileResponse(
        subtitle_path,
        media_type="text/tab-separated-values; charset=utf-8",
        filename=subtitle_path.name,
    )


@app.get("/media/tasks/{task_id}/output/clips/{filename:path}")
async def get_clip(task_id: str, filename: str) -> FileResponse:
    record = _load_task_or_404(task_id)
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid clip filename")
    clips_dir = store.record_path(record, "clips_dir")
    clip_path = store.ensure_task_path(task_id, clips_dir / filename)
    if not clip_path.exists() or not clip_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="clip not found")
    media_type = mimetypes.guess_type(clip_path.name)[0] or "application/octet-stream"
    return FileResponse(clip_path, media_type=media_type, filename=clip_path.name)


async def _save_upload_limited(upload: UploadFile, destination: Path) -> None:
    total_size = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as output:
        while True:
            chunk = await upload.read(CHUNK_SIZE)
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > settings.max_upload_bytes:
                output.close()
                destination.unlink(missing_ok=True)
                raise UploadTooLargeError
            output.write(chunk)


def _load_task_or_404(task_id: str) -> TaskRecord:
    try:
        return store.load(task_id)
    except InvalidTaskIdError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found") from exc
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found") from exc


def _final_subtitle_path(record: TaskRecord) -> Path:
    final_subtitle_path = record.get("final_subtitle_path")
    if isinstance(final_subtitle_path, str) and final_subtitle_path:
        return store.record_path({**record, "subtitle_result_path": final_subtitle_path}, "subtitle_result_path")
    return store.record_path(record, "subtitle_path")


def _parse_tsv_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            stripped = line.rstrip("\n")
            if not stripped:
                continue
            parts = stripped.split("\t")
            if len(parts) < 3:
                continue
            if not rows and parts[0].strip().lower() in {"start", "start_time"}:
                continue
            rows.append(
                {
                    "index": len(rows) + 1,
                    "start": parts[0],
                    "end": parts[1],
                    "text": parts[2],
                }
            )
    return rows


def _list_clips(task_id: str, clips_dir: Path) -> list[dict[str, str]]:
    if not clips_dir.exists():
        return []
    clips: list[dict[str, str]] = []
    for path in sorted(clips_dir.iterdir(), key=lambda item: item.name):
        if not path.is_file():
            continue
        if path.suffix.lower() not in settings.allowed_video_extensions:
            continue
        filename = path.name
        clips.append(
            {
                "filename": filename,
                "url": f"/media/tasks/{task_id}/output/clips/{quote(filename)}",
            }
        )
    return clips
