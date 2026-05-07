# Chalchitra — System Overview

## What It Does

Chalchitra is an AI-powered video clip engine. You upload a raw video or podcast, and the system automatically:

1. Transcribes the audio to English text
2. Generates metadata (title, show notes, tags, chapters)
3. Detects the 3 best viral clip segments using AI
4. Cuts those clips from the source video
5. Renders each clip with animated captions, blurred intro card, and blurred outro card
6. Outputs both a **landscape (16:9)** and a **shorts (9:16)** version of every clip

---

## Service Architecture

```
Browser / UI
     │
     ▼
┌─────────────────────────────────────┐
│  Gateway  (port 8000)               │
│  FastAPI  · SQLite DB  · Dashboard  │
└──────┬──────┬──────┬──────┬────────┘
       │      │      │      │
       ▼      ▼      ▼      ▼
  Transcription  Enrich  Detect  FFmpeg
  (port 8001)  (8002)  (8003)  (8004)
  Whisper      Claude  Claude  FFmpeg +
               API     API     Captions
```

All services share a mounted volume at `shared/volumes/` (`/app/data` inside containers).

---

## Service Responsibilities

| Service | Port | Technology | What it does |
|---|---|---|---|
| **gateway** | 8000 | FastAPI + SQLite | Accepts uploads, orchestrates pipeline, serves UI |
| **transcription** | 8001 | OpenAI Whisper | Speech-to-text with word-level timestamps, translates to English |
| **enrich** | 8002 | Anthropic Claude | Generates title, show notes, tags, chapters from transcript |
| **detect** | 8003 | Anthropic Claude | Finds the 3 best clip segments from transcript/SRT |
| **ffmpeg** | 8004 | FFmpeg + Python | Cuts clips, burns animated captions, creates intro/outro, renders shorts |

---

## Data Models

### Episode
Tracks the full lifecycle of one uploaded video.

| Field | Description |
|---|---|
| `id` | UUID primary key |
| `original_file` | Path to uploaded video |
| `status` | `pending / processing / done` |
| `transcript` | Full English transcript text |
| `words_json` | Word-level timestamps from Whisper (JSON array) |
| `srt_file` | Path to generated `.srt` subtitle file |
| `title` | AI-generated episode title |
| `show_notes` | AI-generated 2-3 sentence summary |
| `tags` | AI-generated tags (JSON array) |
| `chapters` | AI-generated chapters with timestamps (JSON array) |
| `detected_clips` | Raw clip segments from AI detector (JSON array) |
| `generated_clips` | Cut clip file paths from FFmpeg (JSON array) |
| `polished_clips` | Final rendered landscape + shorts paths (JSON array) |

### Job
Tracks the status of each pipeline step per episode.

| Field | Description |
|---|---|
| `episode_id` | Foreign key to Episode |
| `step` | `transcribe / enrich / detect / ffmpeg / render` |
| `status` | `pending / processing / done / failed` |
| `message` | Human-readable progress message |
| `error` | Error detail if failed |

---

## Output Files

For each episode, the following files are written to `shared/volumes/`:

```
{episode_id}.mp4                          ← original upload
{episode_id}.srt                          ← full episode subtitles (English)
{episode_id}_clip0_{title}.mp4            ← raw cut clip
{episode_id}_clip0_landscape.mp4          ← 16:9 final (intro + captions + outro)
{episode_id}_clip0_shorts.mp4             ← 9:16 vertical (intro + captions + outro)
(repeated for clip1, clip2)
```

---

## Dashboard UI

Available at `http://localhost:8000`

- Drag & drop video upload
- Live pipeline progress (auto-refreshes every 3 seconds)
- Download landscape and shorts clips directly from the browser
- Episode history persisted in browser localStorage
