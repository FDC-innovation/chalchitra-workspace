# Chalchitra

**AI-native video & podcast processing pipeline for teachers.**

Upload a lecture. Get a transcript, chapters, social clips, and a thumbnail — automatically.

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?logo=fastapi&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)
![Works on My Machine](https://img.shields.io/badge/works%20on-my%20machine-brightgreen)

---

## Features

- **Automatic transcription** — OpenAI Whisper runs locally, no API key needed; word-level timestamps captured
- **AI-generated metadata** — title, show notes, chapters, and tags via LLM
- **Smart clip detection** — LLM reads the SRT to find the best moments for short-form content
- **Clip generation** — FFmpeg cuts detected segments into ready-to-share MP4 clips
- **Polished social clips** — Remotion renders animated word-by-word captions, intro slide, lower third, and progress bar on each clip
- **Auto thumbnail** — OpenCV extracts a clean keyframe from the video
- **Waveform visualization** — visual audio waveform rendered for every episode
- **Real-time progress** — pipeline status streamed to the browser via Server-Sent Events
- **Review dashboard** — single-page UI to review, edit, download clips, and publish
- **Castopod integration** — publish directly to your self-hosted podcast platform
- **Works offline** — Ollama + Whisper means zero cloud costs for the core pipeline

---

## Dashboard

> _Screenshot coming soon — run it locally and see for yourself._

```
http://localhost:8000
```

---

## Quick Start

```bash
git clone <repo-url> chalchitra-pipeline
cd chalchitra-pipeline
bash start.sh
```

Open `http://localhost:8000`, upload a lecture video, and watch the pipeline run.

> The `start.sh` script creates the virtualenv, installs dependencies, copies `.env.example` → `.env`, and starts the server. You'll need to fill in `.env` before the first real run.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | |
| FFmpeg | Any recent | Must be on `$PATH` |
| Node.js | 18+ | Required for Remotion polished clips |
| Ollama | Latest | Optional — for free local LLM |

**Install FFmpeg:**
```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg
```

**Install Node.js (for Remotion):**
```bash
# macOS
brew install node

# Ubuntu / Debian
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

**Install Ollama (optional but recommended):**
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull tinyllama   # ~1 GB, fast
```

---

## Installation

```bash
# 1. Clone
git clone <repo-url> chalchitra-pipeline
cd chalchitra-pipeline

# 2. Create virtualenv
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure
cp .env.example .env
# Edit .env — see Configuration section below

# 5. Start
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Configuration

All settings live in `.env`. Copy `.env.example` to get started.

### Whisper

| Variable | Default | Description |
|---|---|---|
| `WHISPER_MODEL` | `base` | Model size: `tiny` / `base` / `small` / `medium` / `large` |
| `WHISPER_DEVICE` | `cpu` | Use `cuda` if you have a GPU |

Larger models are more accurate but slower. `base` is a good starting point.

### LLM

| Variable | Default | Description |
|---|---|---|
| `USE_OLLAMA` | `true` | Use local Ollama instead of a cloud API |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server address |
| `OLLAMA_MODEL` | `tinyllama` | Which model to run locally |
| `LLM_API_KEY` | _(empty)_ | API key for cloud LLM fallback (Claude / OpenAI-compatible) |
| `LLM_MODEL` | `claude-sonnet-4-20250514` | Cloud model to use when Ollama is disabled |
| `MAX_CLIPS` | `5` | Maximum number of short clips to generate per episode |

### Remotion (optional)

| Variable | Default | Description |
|---|---|---|
| `ENABLE_REMOTION` | `true` | Set `false` to skip polished clip generation entirely |
| `REMOTION_PROJECT_PATH` | _(auto)_ | Path to the `chalchitra-remotion` project. Defaults to `../chalchitra-remotion` |

When `ENABLE_REMOTION=true`, FFmpeg clips are rendered **without** burned-in subtitles — Remotion adds animated captions instead. Set to `false` to restore subtitle burning and skip the Remotion step.

### Castopod (optional)

| Variable | Description |
|---|---|
| `CASTOPOD_URL` | Base URL of your Castopod instance |
| `CASTOPOD_TOKEN` | API token from Castopod admin |
| `CASTOPOD_PODCAST_ID` | Numeric ID of the podcast to publish to |

---

## LLM Options

Chalchitra tries Ollama first. If Ollama isn't running or `USE_OLLAMA=false`, it falls back to the cloud API.

| Option | RAM Required | Cost | Quality |
|---|---|---|---|
| Ollama `tinyllama` | ~1 GB | Free | Basic — good for titles and tags |
| Ollama `llama3.1:8b` | ~5 GB | Free | Good — better clip detection and show notes |
| Claude API (via `LLM_API_KEY`) | 0 (cloud) | ~$0.01 per video | Best — most accurate clip selection |

```bash
# Pull a better model when you have the RAM
ollama pull llama3.1:8b
# Then set OLLAMA_MODEL=llama3.1:8b in .env
```

> **Tip:** If you see JSON parse errors in the logs, `tinyllama` is hitting its context limit. Switch to `llama3.1:8b` or set a Claude API key.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/upload/` | Upload a media file (mp3, mp4, wav, m4a, …) |
| `GET` | `/api/episodes/` | List all episodes |
| `GET` | `/api/episodes/{id}` | Get a single episode (includes polished_clips) |
| `PATCH` | `/api/episodes/{id}` | Edit title, notes, tags, chapters |
| `GET` | `/api/jobs/{id}/stream` | SSE stream — real-time pipeline progress |
| `GET` | `/api/llm/status` | Check which LLM backend is active |
| `GET` | `/api/remotion/status` | Check Remotion project availability |
| `POST` | `/api/episodes/{id}/publish` | Push to Castopod |

Interactive API docs: `http://localhost:8000/docs`

---

## Pipeline Steps

```
Upload
  │
  ▼
┌──────────────┐
│ 1. transcribe │  Whisper → text + word timestamps + .srt file
└──────┬───────┘
       ▼
┌──────────────┐
│  2. enrich   │  LLM → title, chapters, tags, show notes
└──────┬───────┘
       ▼
┌──────────────┐
│  3. detect   │  LLM reads SRT → picks best clip segments
└──────┬───────┘
       ▼
┌──────────────┐
│  4. ffmpeg   │  Cuts clips (no captions if Remotion enabled)
└──────┬───────┘
       ▼
┌──────────────┐
│  5. remotion │  Animated captions, intro, lower third, progress bar
└──────┬───────┘  (skipped if ENABLE_REMOTION=false)
       ▼
┌──────────────┐
│  6. opencv   │  Extracts keyframe → thumbnail
└──────┬───────┘
       ▼
┌──────────────┐
│  7. publish  │  Marks "ready for review" — teacher approves
└──────────────┘
```

Each step streams its status in real time via SSE at `GET /api/jobs/{id}/stream`.

---

## Project Structure

```
chalchitra-pipeline/
├── app/
│   ├── main.py                  # FastAPI app, router registration, CORS
│   ├── core/
│   │   ├── config.py            # Settings (pydantic-settings + .env)
│   │   └── database.py          # SQLite engine, session factory
│   ├── models/
│   │   └── db.py                # Episode, Job SQLModel definitions
│   ├── api/routes/
│   │   ├── upload.py            # POST /api/upload/
│   │   ├── episodes.py          # GET/PATCH /api/episodes/
│   │   ├── jobs.py              # SSE progress stream
│   │   ├── llm.py               # LLM status endpoint
│   │   ├── enhance.py           # Filler detection endpoint
│   │   ├── remotion.py          # Remotion status endpoint
│   │   └── dashboard.py         # Stats endpoint
│   ├── services/
│   │   ├── whisper.py           # Whisper transcription wrapper
│   │   ├── llm.py               # Ollama / Claude LLM client
│   │   ├── ffmpeg.py            # Clip generation, audio transcode
│   │   ├── opencv.py            # Thumbnail generation
│   │   ├── remotion.py          # Remotion polished clip rendering
│   │   ├── filler_detection.py  # Filler word/pause detection
│   │   └── castopod.py          # Castopod publish client
│   └── workers/
│       ├── pipeline.py          # 7-step orchestrator
│       └── queue.py             # BackgroundTasks queue
├── static/
│   └── index.html               # Single-page dashboard (vanilla JS)
├── uploads/                     # Uploaded media (git-ignored)
├── outputs/                     # Generated clips, thumbnails, waveforms
│   └── <episode_id>/
│       ├── audio.mp3
│       ├── waveform.png
│       ├── thumbnail.jpg
│       ├── clips/               # Raw FFmpeg clips
│       └── polished/            # Remotion-rendered clips
├── .env.example                 # Config template
├── requirements.txt
├── start.sh                     # One-command dev startup
└── docker-compose.yml
```

The Remotion project is expected as a sibling: `../chalchitra-remotion/`

---

## Troubleshooting

**"Ollama not available" in logs**
```bash
ollama serve   # start the Ollama daemon
```

**"No module named X"**
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

**JSON parse errors / bad clip detection**
`tinyllama` struggles with long SRT files. Options:
- Pull a larger model: `ollama pull llama3.1:8b` and set `OLLAMA_MODEL=llama3.1:8b`
- Set `LLM_API_KEY` to use Claude as the backend

**Whisper is slow**
- Switch to a smaller model: `WHISPER_MODEL=tiny` in `.env`
- Set `WHISPER_DEVICE=cuda` if you have an NVIDIA GPU

**FFmpeg not found**
Make sure FFmpeg is installed and on your `$PATH`:
```bash
ffmpeg -version
```

**Remotion not rendering / "npx not found"**
Node.js must be installed and `npm install` must have been run in `chalchitra-remotion/`:
```bash
node --version      # must be 18+
cd ../chalchitra-remotion && npm install
```
Check status at `GET /api/remotion/status`. Set `ENABLE_REMOTION=false` to skip the step entirely.

**Double captions on clips**
If you see captions burned into the video AND Remotion animated captions, `ENABLE_REMOTION` is not being read from `.env`. Confirm the variable is set and restart the server.

---

## Contributing

Pull requests are welcome.

1. Fork the repo and create a branch: `git checkout -b feat/your-feature`
2. Make your changes and test locally
3. Open a PR with a clear description of what changed and why

Please keep PRs focused — one feature or fix per PR.

---

## License

MIT — see [LICENSE](LICENSE).
