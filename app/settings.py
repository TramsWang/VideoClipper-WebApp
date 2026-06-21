"""Application settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


BASE_DIR = Path(__file__).resolve().parents[1]
PipelineMode = Literal["basic", "duration", "llm"]


def _env_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        message = f"{name} must be an integer"
        raise ValueError(message) from exc


def _env_path(name: str, default: str) -> Path:
    raw_value = os.environ.get(name, default)
    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


def _env_mode(name: str, default: PipelineMode) -> PipelineMode:
    value = os.environ.get(name, default)
    if value not in {"basic", "duration", "llm"}:
        message = f"{name} must be one of: basic, duration, llm"
        raise ValueError(message)
    return value  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved runtime settings for the Web App."""

    base_dir: Path
    task_root: Path
    max_upload_mb: int
    config_path: Path
    video_clipper_mode: PipelineMode
    max_running_tasks: int
    templates_dir: Path
    static_dir: Path
    allowed_video_extensions: frozenset[str]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def load_settings() -> Settings:
    max_upload_mb = _env_int("VIDEOCLIPPER_MAX_UPLOAD_MB", 300)
    max_running_tasks = _env_int("VIDEOCLIPPER_MAX_RUNNING_TASKS", 1)
    if max_upload_mb < 1:
        message = "VIDEOCLIPPER_MAX_UPLOAD_MB must be greater than 0"
        raise ValueError(message)
    if max_running_tasks < 1:
        message = "VIDEOCLIPPER_MAX_RUNNING_TASKS must be greater than 0"
        raise ValueError(message)

    return Settings(
        base_dir=BASE_DIR,
        task_root=_env_path("VIDEOCLIPPER_TASK_ROOT", "data/tasks"),
        max_upload_mb=max_upload_mb,
        config_path=_env_path("VIDEOCLIPPER_CONFIG_PATH", "config/video_clipper.yaml"),
        video_clipper_mode=_env_mode("VIDEOCLIPPER_MODE", "llm"),
        max_running_tasks=max_running_tasks,
        templates_dir=BASE_DIR / "app" / "templates",
        static_dir=BASE_DIR / "app" / "static",
        allowed_video_extensions=frozenset({".mp4", ".mov", ".mkv", ".webm", ".avi"}),
    )


settings = load_settings()
