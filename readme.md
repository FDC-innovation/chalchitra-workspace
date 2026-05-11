# 🎬 Chalchitra — AI-Native Video Processing Platform

> Upload a podcast or video. Get back a transcript, metadata, viral clips, and edited Reels-ready vertical videos. Fully automated.

---

## What It Does

Chalchitra takes any video or podcast file and runs it through an AI pipeline:

1. **Transcribes** the audio using OpenAI Whisper
2. **Enriches** with Claude AI — generates title, show notes, tags, and chapters
3. **Detects** the best viral clip moments with timestamps
4. **Cuts** raw clips using FFmpeg
5. **Renders** each clip to 9:16 vertical with animated captions, intro card, and outro card

---

## Architecture

Microservice architecture — each step is an independent FastAPI service running in Docker, orchestrated by n8n.

```
Gateway        :8000  — file upload, database, triggers n8n
Transcription  :8001  — Whisper AI, transcript + SRT + word timestamps
Enrich         :8002  — Claude AI, title / show notes / tags / chapters
Detect         :8003  — Claude AI, viral clip detection with timestamps
FFmpeg         :8004  — cuts raw mp4 clips from original video
Renderer       :8006  — reframe 9:16 + animated captions + intro/outro
n8n            :5678  — workflow orchestration (visual)
Ollama         :11434 — local LLM (optional fallback)
```

### Pipeline Flow

```
Upload video
  → Gateway saves file → triggers n8n webhook
  → Transcribe (Whisper) → transcript + SRT + word timestamps
  → Enrich (Claude) → title, show notes, tags, chapters
  → Detect (Claude) → viral clip timestamps
  → FFmpeg → cuts raw clips
  → Split Clips → n8n splits array into individual items
  → Renderer → per clip: reframe 9:16 + yellow animated captions + intro/outro
  → Collect Results → final output
```

---

## Tech Stack

| Layer            | Technology                 |
| ---------------- | -------------------------- |
| Language         | Python 3.10 / 3.11         |
| API Framework    | FastAPI + Uvicorn          |
| Transcription    | OpenAI Whisper (base, CPU) |
| LLM              | Anthropic Claude Sonnet    |
| Video Processing | FFmpeg                     |
| Rendering        | Pillow + FFmpeg            |
| Orchestration    | n8n                        |
| Containerization | Docker + Docker Compose    |
| Database         | SQLite via SQLModel        |

---

## Project Structure

```
chalchitra-workspace/
├── docker-compose.yml
├── n8n_workflow.json          ← import this into n8n
├── gateway/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py
│       ├── api/routes/
│       ├── core/
│       ├── models/
│       ├── services/
│       └── workers/
├── services/
│   ├── transcription/         ← Whisper, port 8001
│   ├── enrich/                ← Claude metadata, port 8002
│   ├── detect/                ← Claude clip detection, port 8003
│   ├── ffmpeg/                ← video cutting, port 8004
│   └── renderer/              ← animated rendering, port 8006
└── shared/
    └── volumes/               ← uploaded files + generated clips
```

---

## Getting Started

### Prerequisites

- Docker + Docker Compose
- Anthropic API key
- 8GB RAM minimum

### 1. Clone the repo

```bash
git clone https://github.com/FDC-innovation/chalchitra-workspace.git
cd chalchitra-workspace
```

### 2. Create `.env` file

```bash
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

### 3. Create shared volumes folder

```bash
mkdir -p shared/volumes
```

### 4. Start all services

```bash
docker compose up --build
```

First build takes 10-15 minutes (downloads Whisper + PyTorch).

### 5. Import n8n workflow

- Open `http://localhost:5678`
- Top right menu → Import from JSON
- Paste contents of `n8n_workflow.json`
- Save → Click **Listen for test event**

### 6. Upload a video

```bash
curl -X POST http://localhost:8000/api/upload/ \
  -F "file=@/path/to/your/video.mp4"
```

### 7. Check outputs

```bash
ls shared/volumes/*rendered*
```

---

## API Reference

| Service       | Endpoint         | Method | Description       |
| ------------- | ---------------- | ------ | ----------------- |
| Gateway       | `/api/upload/`   | POST   | Upload media file |
| Gateway       | `/api/episodes/` | GET    | List all episodes |
| Gateway       | `/health`        | GET    | Health check      |
| Transcription | `/transcribe`    | POST   | Transcribe file   |
| Enrich        | `/enrich`        | POST   | Generate metadata |
| Detect        | `/detect`        | POST   | Find viral clips  |
| FFmpeg        | `/ffmpeg`        | POST   | Cut video clips   |
| Renderer      | `/render`        | POST   | Render final clip |

---

## n8n Workflow

The workflow JSON is included in `n8n_workflow.json`. It connects all services in sequence:

```
Chalchitra Webhook → Transcribe → Enrich → Detect → FFmpeg → Split Clips → Renderer → Collect Results
```

**Timeouts configured:**

- Transcribe: 9999999ms (unlimited — Whisper on CPU is slow)
- FFmpeg: 300000ms (5 min)
- Renderer: 600000ms (10 min)

---

## Renderer Output

Each final clip includes:

- **9:16 reframe** — cropped and padded for Shorts/Reels
- **Animated captions** — word-by-word yellow highlight
- **Intro card** — 2s black card with title (yellow first line)
- **Outro card** — 3s black card with channel name + CTA

---

## Known Limitations

- Whisper runs on CPU — transcription takes 1-2x real time
- Renderer generates caption frames in Python — slow for long clips
- n8n test webhook mode requires clicking "Listen for test event" before each run
- Transcription container may crash (OOM) on videos longer than 15 minutes

---

## Roadmap

- [ ] Diarization service — speaker detection
- [ ] Frontend dashboard — episode list, clip preview, metadata editor
- [ ] Switch n8n to production webhook mode
- [ ] Redis + Celery queue for production scale
- [ ] Cloud deploy — Railway or AWS ECS
- [ ] GPU support for faster Whisper transcription

---

## Contributors

Built by [FDC Innovation Labs](https://github.com/FDC-innovation)

---

_Chalchitra — From raw video to publish-ready content, automatically._
