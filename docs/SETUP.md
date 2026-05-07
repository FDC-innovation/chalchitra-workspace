# Setup & Running Guide

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Docker Desktop | Latest | Runs all services in containers |
| Git | Any | Version control |

No Python, Node, or FFmpeg installation required on your machine — everything runs inside Docker.

---

## Environment Variables

Create a `.env` file in the project root (already exists):

```env
ANTHROPIC_API_KEY=sk-ant-...       # Required — used by enrich and detect services
```

That's the only required variable. All service URLs are set automatically in docker-compose.

---

## Starting the Project

### First time (full build)
```bash
cd chalchitra-workspace
docker compose up --build
```

First build takes **10–15 minutes** — it downloads Whisper, PyTorch, and all dependencies.

### After first build (normal start)
```bash
docker compose up
```

### Start in background
```bash
docker compose up -d
```

### Stop everything
```bash
docker compose down
```

---

## Rebuilding Individual Services

When you change code in a specific service, rebuild only that service:

```bash
# After changing ffmpeg service code
docker compose up --build ffmpeg

# After changing gateway code
docker compose up --build gateway

# After changing transcription code
docker compose up --build transcription
```

> **Important:** Always rebuild after code changes. Running containers use the old image until rebuilt.

---

## Verifying All Services Are Running

```bash
docker compose ps
```

All should show `running`:
```
chalchitra-gateway        running   0.0.0.0:8000->8000/tcp
chalchitra-transcription  running   0.0.0.0:8001->8001/tcp
chalchitra-enrich         running   0.0.0.0:8002->8002/tcp
chalchitra-detect         running   0.0.0.0:8003->8003/tcp
chalchitra-ffmpeg         running   0.0.0.0:8004->8004/tcp
```

---

## Using the Dashboard

Open your browser at:
```
http://localhost:8000
```

1. Drag & drop a video file (MP4, MOV, MKV, WebM, MP3, M4A)
2. Watch the 5-step pipeline progress update live
3. When all steps show ✅, click **Landscape** or **Shorts** to download

---

## Using the API Directly (Swagger)

```
http://localhost:8000/docs
```

Key endpoints:

| Endpoint | Description |
|---|---|
| `POST /api/upload/` | Upload a video, starts pipeline automatically |
| `GET /api/jobs/{episode_id}` | Check pipeline step statuses |
| `GET /api/episodes/{episode_id}` | Get full episode data including clips |
| `POST /api/steps/run/{episode_id}` | Re-trigger pipeline for an existing episode |
| `POST /api/render/{episode_id}` | Re-run only the render step |

---

## Checking Logs

```bash
# Gateway logs (pipeline progress)
docker logs chalchitra-gateway -f

# Transcription logs
docker logs chalchitra-transcription -f

# FFmpeg render logs
docker logs chalchitra-ffmpeg -f
```

---

## Output Files

All generated files are in:
```
chalchitra-workspace/shared/volumes/
```

Files are also downloadable at:
```
http://localhost:8000/files/{filename}
```

---

## Debugging a Failed Step

1. Check which step failed:
```
GET /api/jobs/{episode_id}
```
Look for `"status": "failed"` and read the `"error"` field.

2. Check service logs:
```bash
docker logs chalchitra-ffmpeg --tail 50
```

3. Re-trigger the full pipeline without re-uploading:
```
POST /api/steps/run/{episode_id}
```

---

## Common Issues

| Error | Cause | Fix |
|---|---|---|
| `All connection attempts failed` | A service container is down | Run `docker compose up -d` |
| `File not found` | Shared volume not mounted | Check `docker compose ps`, ensure volume is mounted |
| `Whisper failed` | Audio format not supported | Convert to MP4/MP3 first |
| `LLM returned invalid JSON` | Claude API rate limit or bad response | Retry — run `POST /api/steps/run/{episode_id}` |
| `create_intro failed` | FFmpeg filter error | Check `docker logs chalchitra-ffmpeg` for details |
| `open //./pipe/dockerDesktopLinuxEngine` | Docker Desktop is not running | Open Docker Desktop and wait for it to fully start |

---

## Folder Structure

```
chalchitra-workspace/
├── docker-compose.yml          ← defines all services
├── .env                        ← API keys
├── shared/
│   └── volumes/               ← all uploaded and generated files
├── gateway/
│   ├── app/
│   │   ├── main.py            ← FastAPI app, routes, file serving
│   │   ├── core/              ← config, database
│   │   ├── models/            ← Episode, Job SQLModel definitions
│   │   ├── api/routes/        ← upload, episodes, jobs, render, steps
│   │   ├── services/
│   │   │   └── pipeline.py    ← main pipeline orchestrator
│   │   └── static/
│   │       └── index.html     ← dashboard UI
│   └── requirements.txt
├── services/
│   ├── transcription/         ← Whisper service
│   ├── enrich/                ← Claude metadata service
│   ├── detect/                ← Claude clip detection service
│   └── ffmpeg/
│       ├── app/
│       │   ├── main.py        ← clip cutting + render endpoint
│       │   └── srt_utils.py   ← SRT parsing + animated ASS generation
│       └── Dockerfile
└── docs/
    ├── OVERVIEW.md            ← system architecture
    ├── CHANGELOG.md           ← all changes with reasons
    ├── PIPELINE.md            ← step by step pipeline details
    └── SETUP.md               ← this file
```
