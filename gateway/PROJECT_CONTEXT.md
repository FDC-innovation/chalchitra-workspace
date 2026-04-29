# Chalchitra Pipeline — Project Context

> Last updated: 2026-04-13. Intended for LLMs joining mid-conversation.

---

## What is Chalchitra?

Chalchitra is an **AI-native video/podcast processing platform** built for teachers. A teacher uploads a raw lecture recording (video or audio) and the system fully automates:

1. **Transcription** — Whisper (local, CPU) → plain text + word-level timestamps + SRT file
2. **AI enrichment** — LLM generates title, show notes, tags, chapters
3. **Smart clip detection** — LLM reads SRT to identify the best moments for short-form content
4. **Clip generation** — FFmpeg cuts detected segments into MP4 clips (captions skipped when Remotion is enabled)
5. **Polished clips** — Remotion renders animated word-by-word captions, intro slide, lower third, progress bar
6. **Thumbnail** — OpenCV extracts best keyframe or gradient fallback
7. **Publish prep** — marks episode "ready for review" in dashboard; teacher reviews then publishes to Castopod

The name "Chalchitra" is Hindi/Urdu for "motion picture / film".

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend framework | FastAPI (Python 3.11) + Uvicorn |
| Database | SQLite via SQLModel/SQLAlchemy |
| Transcription | openai-whisper (`base` model, CPU by default) |
| LLM | Anthropic Claude (`claude-sonnet-4-20250514`) / Ollama (local fallback) |
| Video processing | FFmpeg + ffprobe (subprocess) |
| Polished clips | Remotion (Node.js/React, sibling project `chalchitra-remotion`) |
| Thumbnails | OpenCV + Pillow |
| HTTP client | httpx |
| Task queue | FastAPI BackgroundTasks (in-process, no Redis needed) |
| Frontend | Single vanilla HTML/JS file (`static/index.html`) |
| Deployment | Docker (python:3.11-slim + ffmpeg) |

---

## Project Structure

```
chalchitra-pipeline/
├── app/
│   ├── main.py                   # FastAPI app, lifespan, router registration, CORS
│   ├── core/
│   │   ├── config.py             # Settings (pydantic-settings, reads .env)
│   │   └── database.py           # SQLite engine, session dep, create_db()
│   ├── models/
│   │   └── db.py                 # SQLModel tables: Episode, Job, JobStatus enum
│   ├── api/routes/
│   │   ├── upload.py             # POST /api/upload/ — saves file, creates DB records, fires pipeline
│   │   ├── episodes.py           # GET/PATCH /api/episodes/, POST /{id}/publish
│   │   ├── jobs.py               # GET /api/jobs/{id}/stream (SSE)
│   │   ├── dashboard.py          # GET /api/dashboard/stats
│   │   ├── llm.py                # GET /api/llm/status
│   │   ├── enhance.py            # POST /api/enhance/ (filler detection)
│   │   └── remotion.py           # GET /api/remotion/status
│   ├── workers/
│   │   ├── queue.py              # TaskQueue stub (BackgroundTasks wrapper)
│   │   └── pipeline.py           # run_full_pipeline() — 7-step orchestrator
│   └── services/
│       ├── whisper.py            # transcribe_file() — Whisper in thread executor
│       ├── llm.py                # enrich_episode(), detect_best_clips() — Claude/Ollama
│       ├── ffmpeg.py             # generate_clip(), process_media(), remove_segments()
│       ├── opencv.py             # generate_thumbnail()
│       ├── castopod.py           # publish_to_castopod()
│       ├── filler_detection.py   # detect filler words/pauses
│       └── remotion.py           # render_polished_clip(), check_remotion_available()
├── static/
│   └── index.html                # Full teacher dashboard (single-file SPA, vanilla JS)
├── uploads/                      # Raw uploaded files (UUID-named)
├── outputs/                      # Processed artifacts per episode
│   └── <episode_id>/
│       ├── audio.mp3
│       ├── waveform.png
│       ├── thumbnail.jpg
│       ├── clips/                # Raw FFmpeg clips
│       │   └── 00_clip_title.mp4
│       └── polished/             # Remotion-rendered clips
│           ├── clip_00_props.json
│           └── clip_00_polished.mp4
├── chalchitra.db                 # SQLite database file
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── start.sh
└── .env
```

The Remotion project lives as a sibling directory: `../chalchitra-remotion/`

---

## Data Models

### Episode (SQLModel table)

```python
id              str (UUID, PK)
title           str | None
original_file   str               # path to uploaded file
audio_file      str | None        # path to transcoded MP3
thumbnail       str | None        # path to thumbnail.jpg
highlight_clip  str | None        # path to fallback highlight.mp4 (legacy)
transcript      str | None        # full plain text from Whisper
show_notes      str | None        # AI-generated summary
tags            str | None        # comma-separated string
chapters        str | None        # JSON: [{"start_seconds": 0, "title": "Intro"}, ...]
duration_sec    float | None
words_json      str | None        # JSON: word-level timestamps from Whisper
srt_file        str | None        # path to generated .srt file
detected_clips  str | None        # JSON: LLM-identified clip segments
generated_clips str | None        # JSON: FFmpeg-generated clip file paths + metadata
polished_clips  str | None        # JSON: Remotion-polished clip paths
cleaned_audio   str | None        # path to filler-removed audio
denoised_audio  str | None        # path to noise-reduced audio
status          str | None        # pending | processing | ready_for_review | published
castopod_id     int | None        # set after publish
castopod_url    str | None        # set after publish
created_at      datetime
updated_at      datetime
```

### Job (SQLModel table)

```python
id          str (UUID, PK)
episode_id  str (FK → episode.id)
step        str       # transcribe | enrich | detect | ffmpeg | remotion | opencv | publish
status      JobStatus # pending | processing | done | failed
progress    int       # 0–100
message     str
error       str | None
created_at  datetime
updated_at  datetime
```

Seven Job rows created per episode on upload (one per pipeline step), all starting as `pending`.

---

## Pipeline Flow

```
POST /api/upload/
  └── saves file to uploads/<uuid>.<ext>
  └── creates Episode row
  └── creates 7 Job rows (transcribe, enrich, detect, ffmpeg, remotion, opencv, publish)
  └── fires BackgroundTask → run_full_pipeline(episode_id)

run_full_pipeline(episode_id)
  Step 1: transcribe
    → whisper.transcribe_file()
    → saves ep.transcript, ep.duration_sec, ep.words_json (word timestamps)
    → saves <uuid>.srt alongside the upload; ep.srt_file set

  Step 2: enrich
    → llm.enrich_episode(transcript)
    → Claude/Ollama returns JSON: {title, show_notes, tags[], chapters[]}
    → saves ep.title, ep.show_notes, ep.tags, ep.chapters

  Step 3: detect
    → llm.detect_best_clips(srt_content, transcript)
    → LLM reads SRT, returns best segments: [{start_seconds, end_seconds, title, score}, ...]
    → saves ep.detected_clips (JSON string)

  Step 4: ffmpeg
    → ffmpeg.process_media() → transcodes audio to MP3, generates waveform.png
    → for each detected clip: ffmpeg.generate_clip()
        - Subtitles NOT burned in when settings.ENABLE_REMOTION=True
        - Subtitles burned with force_style when ENABLE_REMOTION=False
    → if no AI clips: fallback to ffmpeg.generate_highlight_clip() (chapter-based)
    → saves ep.audio_file, ep.generated_clips

  Step 5: remotion  (skipped if ENABLE_REMOTION=False or project not found)
    → for each generated clip:
        - filters words from ep.words_json to the clip's time range (time-shifted)
        - copies clip video to chalchitra-remotion/public/ (staticFile() requirement)
        - calls: npx remotion render PodcastClip <output.mp4> --props <props.json>
        - composition selected by format: 9:16=PodcastClip, 16:9=PodcastClip-Horizontal
        - cleans up temp video from public/ after render (finally block)
    → saves ep.polished_clips (JSON: [{original, polished, title}, ...])

  Step 6: opencv
    → opencv.generate_thumbnail()
    → video: samples frames every 10s, scores brightness+sharpness, crops+resizes to 1400×1400
    → audio-only: Pillow teal→purple gradient fallback
    → saves ep.thumbnail

  Step 7: publish
    → marks ep.status = "ready_for_review"
    → teacher reviews in dashboard and manually clicks Publish

  On any step failure: marks job failed, pipeline halts (break in loop)
```

---

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/upload/` | Upload media file, start pipeline |
| GET | `/api/episodes/` | List all episodes (desc by created_at) |
| GET | `/api/episodes/{id}` | Get single episode (all fields including polished_clips) |
| PATCH | `/api/episodes/{id}` | Edit title, show_notes, tags, chapters |
| POST | `/api/episodes/{id}/publish` | Publish to Castopod |
| GET | `/api/jobs/{episode_id}/stream` | SSE stream — live pipeline progress |
| GET | `/api/llm/status` | Which LLM backend is active |
| GET | `/api/remotion/status` | Remotion project availability |
| GET | `/api/dashboard/stats` | total/published/draft counts |
| GET | `/outputs/{path}` | Static file serving for thumbnails/clips |
| GET | `/health` | Health check |
| GET | `/` | Serve the dashboard HTML |

---

## Configuration (.env)

```bash
# Whisper
WHISPER_MODEL=base          # tiny | base | small | medium | large
WHISPER_DEVICE=cpu          # cpu | cuda

# LLM — Ollama (local, free)
USE_OLLAMA=true
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=tinyllama

# LLM — Claude fallback
LLM_API_KEY=sk-ant-...
LLM_MODEL=claude-sonnet-4-20250514

# Clip settings
USE_LLM_FOR_CLIPS=true
DEFAULT_CLIP_DURATION=45
MAX_CLIPS=5

# Remotion
REMOTION_PROJECT_PATH=      # leave empty to auto-detect ../chalchitra-remotion
ENABLE_REMOTION=true        # set false to skip polished clip generation

# Castopod
CASTOPOD_URL=http://localhost:8080
CASTOPOD_TOKEN=...
CASTOPOD_PODCAST_ID=1

# Database
DATABASE_URL=sqlite:///./chalchitra.db
```

---

## Caption Handling Logic

This is a critical design decision to avoid double captions:

- When `ENABLE_REMOTION=True`: FFmpeg clips are rendered **without** burned-in subtitles. Remotion adds word-by-word animated captions instead.
- When `ENABLE_REMOTION=False`: FFmpeg burns the `.srt` file into clips using `subtitles=` filter with `force_style`.

The check lives in two places in `app/services/ffmpeg.py`:
- `generate_clip()` line: `if burn_subtitles and not settings.ENABLE_REMOTION and Path(srt_path).exists():`
- `generate_vertical_clip()` line: `if not settings.ENABLE_REMOTION and Path(srt_path).exists():`

---

## Remotion Integration Details

- **Project location**: `../chalchitra-remotion/` (sibling to this repo), auto-detected via `Path(settings.BASE_DIR).parent / "chalchitra-remotion"`.
- **Availability check**: `check_remotion_available()` verifies directory, `package.json`, and `node_modules` exist.
- **Video file handling**: Remotion's `staticFile()` only resolves files inside `public/`. The service copies each clip to `chalchitra-remotion/public/temp_{episode_id}_{clip_index}.mp4` before rendering, then deletes it in a `finally` block.
- **Props format**: props JSON is written to `outputs/{episode_id}/polished/clip_XX_props.json` and passed via `--props` flag.
- **Word timestamps**: Whisper's word-level output (`ep.words_json`) is filtered to each clip's time range and time-shifted (words start at 0 relative to clip start).
- **Compositions**: `PodcastClip` (9:16), `PodcastClip-Horizontal` (16:9), `PodcastClip-Square` (1:1). Default is `9:16`.
- **Timeout**: 5 minutes per clip via `subprocess.run(..., timeout=300)`.

---

## Frontend (static/index.html)

Single-file vanilla JS SPA, no build step. Three sections:

- **New Episode** — drag-and-drop upload, live pipeline progress (SSE, 7 steps), episode editor, polished clips viewer, publish button
- **My Episodes** — list with thumbnail, date, duration, clip count, Published/Draft badge
- **Stats** — total/published/draft counts + LLM/system status

**Pipeline step display** (`STEP_META` object):

| Key | Icon | Label |
|---|---|---|
| transcribe | 🗣 | Whisper Transcription |
| enrich | 🤖 | AI Enrichment |
| detect | 🎯 | Smart Clip Detection |
| ffmpeg | ✂️ | FFmpeg Processing |
| remotion | ✨ | Polishing Clips |
| opencv | 🖼 | Thumbnail Generation |
| publish | 📡 | Publish Prep |

**Polished clips**: shown in a separate section below raw clips. Each card has an inline `<video>` player, download polished button, and download raw button. Section hidden if no polished clips.

**Key JS functions**:
- `startUpload(file)` — POST to upload, init SSE
- `initStepUI()` — renders step rows from `STEP_META`
- `startSSE(episodeId)` — streams job updates, triggers `loadEpisodeIntoEditor` when all done/failed
- `loadEpisodeIntoEditor(id)` — GETs episode, populates all fields, calls `renderGeneratedClips` and `renderPolishedClips`
- `renderGeneratedClips(id, json, highlight)` — raw FFmpeg clips
- `renderPolishedClips(json)` — Remotion polished clips
- `clipToUrl(filePath)` — converts absolute path to `/outputs/...` URL

---

## Castopod Integration

`app/services/castopod.py` — `publish_to_castopod(ep: Episode)`:
1. Upload audio to `POST /api/v1/podcasts/{podcast_id}/media` → `media_id`
2. Create episode at `POST /api/v1/podcasts/{podcast_id}/episodes`
3. Add chapters one-by-one at `POST /api/v1/podcasts/{podcast_id}/episodes/{ep_id}/chapters`
4. Returns `{id, url}` → saved to `ep.castopod_id` and `ep.castopod_url`

Auth: Bearer token via `CASTOPOD_TOKEN`.

---

## Key Design Decisions

- **No Redis** — queue is FastAPI `BackgroundTasks` (in-process). `queue.py` notes ARQ/Celery as upgrade path.
- **Pipeline halts on first failure** — `break` in step loop; downstream steps won't run.
- **Publish is manual** — Step 7 marks "ready for review" only; teacher reviews in UI then clicks Publish.
- **Whisper in thread executor** — avoids blocking async event loop. Model cached with `@lru_cache`.
- **Claude JSON parsing** — strips markdown fences with regex before `json.loads`. Graceful fallback on invalid JSON.
- **Chapters stored as JSON string** — `ep.chapters` is a `str` field containing JSON. Both `json.loads` and `ast.literal_eval` tried when parsing.
- **LLM transcript truncated to 8000 chars** — prevents token limit issues.
- **Thumbnail scoring** — `sharpness * 0.7 + brightness * 0.3`; dark (<30) or blown-out (>220) frames rejected.
- **Allowed upload formats** — `.mp3 .mp4 .wav .m4a .ogg .webm .mkv .mov`
- **Word timestamps** — Whisper `word_timestamps=True` result stored as `ep.words_json`. Used by Remotion step to time-shift words per clip.
- **Remotion temp file cleanup** — `finally` block in `render_polished_clip` ensures `public/temp_*` is always deleted even on failure or timeout.
- **Double-caption prevention** — `ENABLE_REMOTION=True` disables FFmpeg subtitle burning in both `generate_clip` and `generate_vertical_clip`.

---

## Running Locally

```bash
pip install -r requirements.txt
cp .env.example .env      # fill in LLM_API_KEY etc.
uvicorn app.main:app --reload --port 8000
# Dashboard: http://localhost:8000
```

For Remotion (optional):
```bash
cd ../chalchitra-remotion
npm install
# ENABLE_REMOTION=true in .env
```

With Docker:
```bash
docker compose up
```

---

## File Naming Conventions

- Uploaded files: `uploads/<uuid>.<ext>`
- SRT files: `uploads/<uuid>.srt` (same UUID, auto-generated alongside upload)
- Audio: `outputs/<episode_id>/audio.mp3`
- Waveform: `outputs/<episode_id>/waveform.png`
- Thumbnail: `outputs/<episode_id>/thumbnail.jpg`
- Raw clips: `outputs/<episode_id>/clips/00_clip_title.mp4`
- Polished clips: `outputs/<episode_id>/polished/clip_00_polished.mp4`
- Remotion props: `outputs/<episode_id>/polished/clip_00_props.json`
- Episode ID = UUID4 string, used as `Episode.id` in DB and as the output directory name
