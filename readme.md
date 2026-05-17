# 🎬 Chalchitra — AI-Native Video Processing Platform

> Upload a podcast or video. Get back a transcript, metadata, viral clips, and edited Reels-ready vertical videos. Fully automated with human-in-the-loop review at every critical step.

---

## What It Does

Chalchitra takes any video or podcast recording and runs it through a fully automated AI pipeline — with optional human review at key checkpoints before expensive processing happens.

**Two complete pipelines:**

- **Clips Pipeline** — Extract viral short-form clips from any video. Outputs 9:16 vertical videos ready for Reels, Shorts, and TikTok.
- **Podcast Pipeline** — Full podcast post-production. Removes silence, detects speakers, generates chapters, then extracts clips.

---

## What Changed — n8n → LangGraph

The original system used n8n as its orchestrator. This branch replaces it entirely with a Python-native LangGraph state machine.

| | Before (n8n) | Now (LangGraph) |
|---|---|---|
| Orchestrator | Visual JSON workflow | Python StateGraph |
| Human review | Not possible | HITL at every checkpoint |
| Error recovery | Full restart required | Resume from last checkpoint |
| State management | Implicit, fragile | Typed TypedDict, SQLite persisted |
| Version control | JSON blob | Pure Python, Git-native |
| Prompt control | Hardcoded | User-editable per run |
| GPU support | None | Auto-detects CUDA, falls back to CPU |

---

## Architecture — 13 Microservices

Every service is an independent FastAPI app in its own Docker container. All share one volume at `/app/shared/volumes`.

```
gateway             :8000  — file upload, SQLite DB, triggers orchestrator
transcription       :8001  — Whisper AI (English/general), GPU-aware
enrich              :8002  — Claude Sonnet, metadata generation
detect              :8003  — Claude Sonnet, viral clip detection
ffmpeg              :8004  — cuts raw mp4 clips
renderer            :8006  — 9:16 reframe + animated captions + cards
orchestrator        :8007  — LangGraph state machine (replaces n8n)
silence_detector    :8008  — FFmpeg silencedetect, finds silence segments
auto_editor         :8010  — removes silence, produces edited mp4 + EDL
transcription_indic :8011  — faster-whisper, Hindi/Hinglish, GPU-aware
diarization         :8012  — resemblyzer + KMeans, Speaker A/B detection
ui                  :3000  — browser pipeline console (nginx)
ollama              :11434 — local LLM fallback (optional)
```

---

## Clips Pipeline — Full Flow

```
POST /api/upload/
  ↓
Gateway — saves file, creates Episode + Job records
  ↓
Orchestrator — LangGraph ainvoke() begins
  ↓
[transcribe] — Whisper → text + word timestamps + SRT
  ↓
✋ HITL #1 — Pipeline pauses here
   User can inject custom Claude prompts before AI runs
   POST /pipeline/approve {enrich_prompt, detect_prompt}
  ↓
[enrich] — Claude → title, show_notes, tags, chapters
  ↓
[detect] — Claude → viral clip timestamps + reasons
  ↓
[ffmpeg] — cuts raw mp4 clips from original video
  ↓
[filter_clips] — validates each clip (status=done, file_path exists)
  ↓
✋ HITL #2 — Pipeline pauses here
   User reviews clips in UI, unchecks bad ones
   POST /pipeline/approve {approved_clips: [...]}
  ↓
[renderer] — per clip: 9:16 reframe + animated captions + intro/outro
  ↓
pipeline_status: completed
Rendered clips at shared/volumes/{episode_id}/*_final.mp4
Videos stream at http://localhost:3000/media/{episode_id}/{filename}
```

---

## Podcast Pipeline — Full Flow

```
POST /podcast/start
  ↓
[detect_silence] — FFmpeg silencedetect → speech/silence segments
  ↓
✋ HITL #1 — Review edit decisions before cutting
   POST /podcast/approve {updates: {approved_edits: [...]}}
  ↓
[auto_edit] — FFmpeg concat → silence removed → edited mp4
  ↓
[transcribe] — Whisper on edited file (not original)
  ↓
[diarize] — resemblyzer → Speaker_A / Speaker_B segments
  ↓
[enrich] — Claude → title, show_notes, chapters (with speaker context)
  ↓
[structure] — Claude → chapter structure
  ↓
✋ HITL #2 — Review chapter structure
   POST /podcast/approve {updates: {approved_chapters: [...]}}
  ↓
[detect_clips] — Claude → viral clip timestamps
  ↓
✋ HITL #3 — Approve clips before rendering
   POST /podcast/approve {updates: {approved_clips: [...]}}
  ↓
[renderer] — 9:16 vertical clips with captions
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| API Framework | FastAPI + Uvicorn |
| Orchestration | LangGraph (replaces n8n) |
| Transcription (EN) | OpenAI Whisper via transformers |
| Transcription (HI) | faster-whisper small, language=hi |
| LLM | Anthropic Claude Sonnet |
| Speaker Detection | resemblyzer + scikit-learn KMeans |
| Silence Detection | FFmpeg silencedetect filter |
| Video Processing | FFmpeg |
| Rendering | Pillow + FFmpeg |
| State Persistence | SQLite via LangGraph checkpointer |
| Database | SQLite via SQLModel |
| Containerization | Docker + Docker Compose |
| UI | Nginx + vanilla HTML/JS |

---

## Project Structure

```
chalchitra-workspace/
├── docker-compose.yml           ← CPU mode (default)
├── docker-compose.gpu.yml       ← GPU override for NVIDIA machines
├── readme.md
├── gateway/                     ← :8000 file upload + DB
│   └── app/
│       ├── main.py
│       ├── api/routes/upload.py
│       ├── core/config.py
│       ├── core/database.py
│       └── models/db.py
├── orchestrator/                ← :8007 LangGraph orchestrator
│   └── app/
│       ├── main.py              ← FastAPI + all pipeline endpoints
│       ├── state.py             ← ChalchitraState + PodcastState TypedDicts
│       ├── graph.py             ← Clips pipeline StateGraph
│       ├── podcast_graph.py     ← Podcast pipeline StateGraph
│       └── nodes/               ← one file per node
│           ├── transcribe.py
│           ├── enrich.py
│           ├── detect.py
│           ├── ffmpeg.py
│           ├── filter_clips.py
│           └── renderer.py
├── services/
│   ├── transcription/           ← :8001 Whisper English
│   ├── transcription_indic/     ← :8011 faster-whisper Hindi
│   ├── enrich/                  ← :8002 Claude metadata
│   ├── detect/                  ← :8003 Claude clip detection
│   ├── ffmpeg/                  ← :8004 video cutting
│   ├── renderer/                ← :8006 9:16 rendering
│   ├── silence_detector/        ← :8008 FFmpeg silence detection
│   ├── auto_editor/             ← :8010 silence removal
│   ├── diarization/             ← :8012 speaker detection
│   └── ui/                      ← :3000 browser console
│       ├── index.html
│       └── nginx.conf
└── shared/
    └── volumes/                 ← ALL file I/O goes here
        ├── {episode_id}.mp4                    ← original upload
        ├── {episode_id}_clip{N}_{title}.mp4   ← raw cut clips
        └── {episode_id}/
            └── {title}_final.mp4              ← rendered 9:16 clips
```

---

## Getting Started

### Prerequisites

- Docker + Docker Compose
- Anthropic API key
- 8GB RAM minimum (16GB recommended)

### 1. Clone and switch to LangGraph branch

```bash
git clone https://github.com/FDC-innovation/chalchitra-workspace.git
cd chalchitra-workspace
git checkout feature/langgraph-orchestrator
```

### 2. Create `.env` file

```bash
echo "ANTHROPIC_API_KEY=sk-ant-your-key-here" > .env
```

### 3. Create required folders

```bash
mkdir -p shared/volumes
```

### 4. Start all services

**CPU mode (Mac M1/M2, any machine):**
```bash
docker compose up -d --remove-orphans
```

**GPU mode (NVIDIA only — RTX 3000/4000 series):**
```bash
# Requires nvidia-container-toolkit installed on host
# See: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

GPU mode automatically:
- Loads Whisper large-v3 instead of small/base
- Uses CUDA float16 instead of CPU int8
- ~10x faster transcription on RTX 3090

First build takes 10-20 minutes depending on internet speed.

### 5. Verify all services are running

```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```

All 13 containers should show `Up` or `healthy`.

### 6. Open the UI

```
http://localhost:3000
```

Status dot should be green. Select your pipeline and upload a video.

---

## Using the UI

1. **Select pipeline** — Clips Pipeline or Podcast Pipeline
2. **Drop video** or click to select (mp4, mp3, wav, m4a, webm, mkv, mov)
3. **Click Start Pipeline**
4. **Watch the progress bar** — Whisper → Enrich → Detect → FFmpeg → Filter → Render
5. **Review at HITL checkpoints** — edit Claude prompts, approve or remove clips
6. **Watch rendered clips** in browser — videos play inline

---

## API Reference

### Gateway — :8000

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/upload/` | Upload media file, returns episode_id |
| GET | `/api/episodes/` | List all episodes |
| GET | `/health` | Health check |

### Orchestrator — :8007

| Method | Endpoint | Description |
|---|---|---|
| POST | `/pipeline/start` | Start clips pipeline |
| GET | `/pipeline/status/{episode_id}` | Get current state + interrupt info |
| POST | `/pipeline/approve` | Inject prompts or approve clips |
| POST | `/pipeline/reject` | Reject and cancel |
| POST | `/podcast/start` | Start podcast pipeline |
| GET | `/podcast/status/{episode_id}` | Get podcast pipeline state |
| POST | `/podcast/approve` | Approve at any podcast checkpoint |

### Status Response Schema

```json
{
  "episode_id": "uuid",
  "state": {
    "pipeline_status": "awaiting_approval",
    "transcript_text": "...",
    "title": "...",
    "detected_clips": [...],
    "cut_clips": [...],
    "rendered_clips": [...]
  },
  "next": ["renderer"],
  "at_interrupt": true
}
```

`at_interrupt: true` means the pipeline is paused and waiting for your approval.

### Clips Pipeline — HITL #1 (Prompt Customization)

```bash
curl -X POST http://localhost:8007/pipeline/approve \
  -H "Content-Type: application/json" \
  -d '{
    "episode_id": "your-episode-id",
    "enrich_prompt": "Generate a clickbait title and 5 key points",
    "detect_prompt": "Find clips where speaker makes a surprising claim, under 60 seconds",
    "approved_clips": []
  }'
```

### Clips Pipeline — HITL #2 (Clip Approval)

```bash
curl -X POST http://localhost:8007/pipeline/approve \
  -H "Content-Type: application/json" \
  -d '{
    "episode_id": "your-episode-id",
    "approved_clips": [
      {
        "title": "Clip Title",
        "start_seconds": 0.0,
        "end_seconds": 60.0,
        "file_path": "/app/shared/volumes/{episode_id}_clip0_title.mp4"
      }
    ]
  }'
```

### Diarization — Standalone

```bash
curl -X POST http://localhost:8012/diarize \
  -H "Content-Type: application/json" \
  -d '{
    "episode_id": "test",
    "file_path": "/app/shared/volumes/your-file.mp4",
    "num_speakers": 2
  }'
```

Returns `Speaker_A` / `Speaker_B` segments with timestamps.

### Hinglish Transcription

```bash
curl -X POST http://localhost:8007/pipeline/start \
  -H "Content-Type: application/json" \
  -d '{
    "file_path": "/app/shared/volumes/your-file.mp4",
    "transcription_engine": "indic"
  }'
```

Use `"indic"` for Hindi/Hinglish content, `"whisper"` (default) for English.

---

## Renderer Output

Each final clip includes:

- **9:16 reframe** — cropped and padded for Shorts/Reels
- **Animated captions** — word-by-word yellow highlight synced to audio
- **Intro card** — 2s black card with episode title
- **Outro card** — 3s black card with channel name + CTA

Files saved at `shared/volumes/{episode_id}/{title}_final.mp4`
Stream in browser at `http://localhost:3000/media/{episode_id}/{title}_final.mp4`

---

## Running on GPU (NVIDIA)

### Requirements

- NVIDIA GPU (RTX 3000 series or newer recommended)
- [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) installed on host
- CUDA 12.1 compatible driver

### Install nvidia-container-toolkit (Ubuntu)

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### Start with GPU

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

### Performance comparison

| Task | CPU (M1) | GPU (RTX 3090) |
|---|---|---|
| Whisper model | small/base | large-v3 |
| 3 min video transcription | 8-15 min | 20-40 sec |
| Diarization 30 min audio | 5 min | 20 sec |
| Full clips pipeline | 10-15 min | 1-2 min |

---

## Known Limitations

- Whisper on CPU is slow — 1-2x real time for English, 4-6x for Hinglish
- Podcast pipeline services are built and wired but not battle-tested on long recordings
- Checkpoint database is not volume-mounted — paused pipelines lost on `docker compose down`
- UI prompt customization panel is API-only — use curl or Postman for HITL #1
- No noise removal service yet (roadmap)
- No speaker tracking / auto-framing (roadmap)

---

## Roadmap

- [ ] Mount checkpoint DB to volume (persist across restarts)
- [ ] Prompt customization panel in UI (currently API-only)
- [ ] Noise removal service (noisereduce)
- [ ] Redis + Celery queue for concurrent uploads
- [ ] Full podcast pipeline battle-test on 60+ min recordings
- [ ] Cloud deploy — Railway or AWS ECS
- [ ] Speaker auto-framing with OpenCV

---

## Contributors

Built by [FDC Innovation Labs](https://github.com/FDC-innovation)

Branch: `feature/langgraph-orchestrator`

---

*Chalchitra — From raw video to publish-ready content, automatically.*