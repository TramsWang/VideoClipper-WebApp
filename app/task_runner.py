"""Background execution for VideoClipper tasks."""

from __future__ import annotations

import contextlib
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Lock
from typing import Any

from app.settings import Settings
from app.task_store import TaskStore, now_iso


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class TaskRunner:
    """Run auto_clipper jobs in a local background executor."""

    def __init__(self, settings: Settings, store: TaskStore) -> None:
        self.settings = settings
        self.store = store
        self._executor: ThreadPoolExecutor | None = None
        self._base_config: Any | None = None
        self._auto_logger_name = "auto_clipper"
        self._stdio_lock = Lock()

    def startup(self) -> None:
        from auto_clipper import AUTO_CLIPPER_LOGGER_NAME, load_config

        self._base_config = load_config(self.settings.config_path)
        self._auto_logger_name = AUTO_CLIPPER_LOGGER_NAME
        self._executor = ThreadPoolExecutor(
            max_workers=self.settings.max_running_tasks,
            thread_name_prefix="videoclipper-task",
        )

    def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=False)
            self._executor = None

    def submit(self, task_id: str) -> Future[None]:
        if self._executor is None:
            message = "task runner is not started"
            raise RuntimeError(message)
        return self._executor.submit(self._run_task, task_id)

    def _run_task(self, task_id: str) -> None:
        record = self.store.update(task_id, status="running", started_at=now_iso(), error=None)
        log_path = self.store.record_path(record, "log_path")
        input_path = self.store.record_path(record, "input_path")
        subtitle_path = self.store.record_path(record, "subtitle_path")
        clips_dir = self.store.record_path(record, "clips_dir")
        clips_dir.mkdir(parents=True, exist_ok=True)

        task_logger = logging.getLogger(f"videoclipper.task.{task_id}")
        task_logger.setLevel(logging.INFO)
        task_logger.propagate = False

        auto_logger = logging.getLogger(self._auto_logger_name)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        task_logger.addHandler(file_handler)
        auto_logger.addHandler(file_handler)

        try:
            result = self._execute_clipper(
                task_id=task_id,
                language=str(record["language"]),
                input_path=input_path,
                subtitle_path=subtitle_path,
                clips_dir=clips_dir,
                log_path=log_path,
                task_logger=task_logger,
            )
            self.store.update(
                task_id,
                status="succeeded",
                finished_at=now_iso(),
                error=None,
                final_subtitle_path=self.store.display_path(result.final_tsv_path),
                clip_paths=[self.store.display_path(path) for path in result.clip_paths],
            )
        except Exception as exc:
            task_logger.exception("Task %s failed", task_id)
            self.store.update(
                task_id,
                status="failed",
                finished_at=now_iso(),
                error=str(exc),
            )
        finally:
            auto_logger.removeHandler(file_handler)
            task_logger.removeHandler(file_handler)
            file_handler.close()

    def _execute_clipper(
        self,
        *,
        task_id: str,
        language: str,
        input_path: Path,
        subtitle_path: Path,
        clips_dir: Path,
        log_path: Path,
        task_logger: logging.Logger,
    ) -> Any:
        from auto_clipper import run_clipper

        if self._base_config is None:
            message = "base auto_clipper config is not loaded"
            raise RuntimeError(message)

        task_config = replace(
            self._base_config,
            subtitle=replace(self._base_config.subtitle, language=language),
        )

        # stdout/stderr redirection is process-global, so keep the actual API call serialized.
        with self._stdio_lock:
            with log_path.open("a", encoding="utf-8", buffering=1) as log_file:
                with contextlib.redirect_stdout(log_file), contextlib.redirect_stderr(log_file):
                    task_logger.info("Task %s started", task_id)
                    task_logger.info(
                        "Running auto_clipper API: input=%s output=%s mode=%s language=%s clips_dir=%s",
                        input_path,
                        subtitle_path,
                        self.settings.video_clipper_mode,
                        language,
                        clips_dir,
                    )
                    result = run_clipper(
                        input_path,
                        subtitle_path,
                        video_clip_dir=clips_dir,
                        mode=self.settings.video_clipper_mode,
                        config=task_config,
                    )
                    task_logger.info("Task %s succeeded: final_tsv=%s clips=%d", task_id, result.final_tsv_path, len(result.clip_paths))
                    return result
