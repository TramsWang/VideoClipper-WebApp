# VideoClipper-WebApp

A minimal FastAPI Web App wrapper for the `auto_clipper` Python toolkit.

## Features

- Upload one video file up to 300 MB.
- Select Chinese or English for transcription.
- Run `auto_clipper` through its Python API with a shared Web App config file.
- Poll task logs from `data/tasks/{task_id}/logs/run.log`.
- Show the final TSV subtitles and generated video clips after completion.

## Setup

Install the private `VideoClipper` toolkit first, then install the Web App dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e "/home/ruoyu/VideoClipper[asr]"
python -m pip install -r requirements.txt
```

Make sure FFmpeg and ffprobe are available on `PATH`. If the ASR dependencies are already installed in the runtime environment, installing `/home/ruoyu/VideoClipper` without `[asr]` is also fine.

## Run

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 12345
```

Open `http://127.0.0.1:12345`.

## Configuration

The Web App uses `config/video_clipper.yaml` for all tasks. The upload page language selection overrides only `subtitle.language` for the current task.

Environment variables:

| Name | Default | Description |
| --- | --- | --- |
| `VIDEOCLIPPER_TASK_ROOT` | `data/tasks` | Task data root |
| `VIDEOCLIPPER_MAX_UPLOAD_MB` | `300` | Upload size limit |
| `VIDEOCLIPPER_CONFIG_PATH` | `config/video_clipper.yaml` | Shared `auto_clipper` config |
| `VIDEOCLIPPER_MODE` | `duration` | `basic`, `duration`, or `llm` |
| `VIDEOCLIPPER_MAX_RUNNING_TASKS` | `1` | Local worker count |

Task data is stored under `data/tasks/{task_id}` and is intended to be deleted manually.
