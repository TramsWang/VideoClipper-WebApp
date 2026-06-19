"""Task metadata and task directory helpers."""

from __future__ import annotations

import json
import re
import secrets
import shutil
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from app.settings import Settings


TASK_ID_PATTERN = re.compile(r"^\d{8}_\d{6}_[A-Za-z0-9]{8}$")
TaskRecord = dict[str, Any]


class TaskNotFoundError(LookupError):
    """Raised when a task cannot be found."""


class InvalidTaskIdError(ValueError):
    """Raised when a task id does not match the expected format."""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class TaskStore:
    """Read and write task records under the configured task root."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = Lock()

    def ensure_initialized(self) -> None:
        self.settings.task_root.mkdir(parents=True, exist_ok=True)

    def create_task(self, *, language: str, original_filename: str, input_extension: str) -> TaskRecord:
        task_id = self._new_task_id()
        task_dir = self.task_dir(task_id)
        upload_dir = task_dir / "upload"
        output_dir = task_dir / "output"
        clips_dir = output_dir / "clips"
        logs_dir = task_dir / "logs"

        upload_dir.mkdir(parents=True, exist_ok=False)
        clips_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)

        input_path = upload_dir / f"input{input_extension}"
        subtitle_path = output_dir / "subtitles.tsv"
        log_path = logs_dir / "run.log"
        log_path.touch()

        record: TaskRecord = {
            "task_id": task_id,
            "status": "uploaded",
            "language": language,
            "mode": self.settings.video_clipper_mode,
            "config_path": self.display_path(self.settings.config_path),
            "original_filename": original_filename,
            "input_path": self.display_path(input_path),
            "subtitle_path": self.display_path(subtitle_path),
            "final_subtitle_path": None,
            "clips_dir": self.display_path(clips_dir),
            "log_path": self.display_path(log_path),
            "created_at": now_iso(),
            "started_at": None,
            "finished_at": None,
            "error": None,
        }
        self.save(record)
        return record

    def load(self, task_id: str) -> TaskRecord:
        task_json = self._task_json_path(task_id)
        if not task_json.exists():
            raise TaskNotFoundError(task_id)
        with task_json.open("r", encoding="utf-8") as file:
            loaded = json.load(file)
        if not isinstance(loaded, dict):
            raise TaskNotFoundError(task_id)
        return loaded

    def save(self, record: TaskRecord) -> None:
        task_id = str(record["task_id"])
        task_json = self._task_json_path(task_id)
        task_json.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = task_json.with_name("task.json.tmp")
        with self._lock:
            with tmp_path.open("w", encoding="utf-8") as file:
                json.dump(record, file, ensure_ascii=False, indent=2)
                file.write("\n")
            tmp_path.replace(task_json)

    def update(self, task_id: str, **changes: Any) -> TaskRecord:
        with self._lock:
            record = self.load(task_id)
            record.update(changes)
            task_json = self._task_json_path(task_id)
            tmp_path = task_json.with_name("task.json.tmp")
            with tmp_path.open("w", encoding="utf-8") as file:
                json.dump(record, file, ensure_ascii=False, indent=2)
                file.write("\n")
            tmp_path.replace(task_json)
            return record

    def cleanup(self, task_id: str) -> None:
        task_dir = self.task_dir(task_id)
        if task_dir.exists():
            shutil.rmtree(task_dir)

    def task_dir(self, task_id: str) -> Path:
        self._validate_task_id(task_id)
        return (self.settings.task_root / task_id).resolve()

    def record_path(self, record: TaskRecord, key: str) -> Path:
        value = record.get(key)
        if not isinstance(value, str) or not value:
            message = f"missing path field: {key}"
            raise ValueError(message)
        path = Path(value)
        if not path.is_absolute():
            path = self.settings.base_dir / path
        return self.ensure_task_path(str(record["task_id"]), path)

    def ensure_task_path(self, task_id: str, path: Path) -> Path:
        task_dir = self.task_dir(task_id)
        resolved = path.resolve()
        if resolved != task_dir and task_dir not in resolved.parents:
            message = f"path is outside task directory: {resolved}"
            raise ValueError(message)
        return resolved

    def _task_json_path(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "task.json"

    def _new_task_id(self) -> str:
        while True:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            token = secrets.token_hex(4)
            task_id = f"{timestamp}_{token}"
            if not (self.settings.task_root / task_id).exists():
                return task_id

    def _validate_task_id(self, task_id: str) -> None:
        if not TASK_ID_PATTERN.fullmatch(task_id):
            raise InvalidTaskIdError(task_id)

    def display_path(self, path: Path) -> str:
        resolved = path.resolve()
        try:
            return str(resolved.relative_to(self.settings.base_dir))
        except ValueError:
            return str(resolved)
