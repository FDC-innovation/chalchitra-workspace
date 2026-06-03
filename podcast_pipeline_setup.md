# Chalchitra — Podcast Pipeline

The podcast pipeline takes a raw video file and produces a fully edited podcast MP4 with chapter cards, captions, and a final stitched output.

---

## How It Works

```
Video → Transcribe → Chapter Detection → Cut → Render → Stitch → podcast_final.mp4
```

| Step | What happens |
|------|-------------|
| Transcribe | Whisper transcribes the video, returns words + timestamps |
| Chapter Detection | LLaMA 3.1 (via Groq API) reads the transcript and generates 4–8 chapters with titles, subtitles, and timestamps |
| Cut | ffmpeg cuts one MP4 per chapter from the source video |
| Render | Each chapter gets a blurred-frame title card + caption burn |
| Stitch | All rendered chapters are concatenated into `podcast_final.mp4` |

---

## Prerequisites

- Docker Desktop running
- Groq API key — get one at [console.groq.com](https://console.groq.com)

---

## Setup

**1. Clone and checkout the branch**
```bash
git clone https://github.com/FDC-innovation/chalchitra-workspace
cd chalchitra-workspace
git checkout feature/langgraph-v2
```

**2. Add your Groq API key to `docker-compose.yml`**

Find the `orchestrator` service and set:
```yaml
environment:
  - GROQ_API_KEY=your_key_here
```

**3. Start all services**
```bash
docker compose up -d --build
```

Wait ~30 seconds for all services to be healthy:
```bash
docker compose ps
```

---

## Running the Pipeline

```bash
./run_podcast.sh /path/to/your/video.mp4
```

That's it. The script handles episode ID creation, file copying, and API call automatically.

---

## Watching Progress

```bash
tail -f shared/volumes/pipeline.log
```

You'll see this sequence:
```
Transcribe done — XXXX words
podcast_chapters done — 6 chapters
podcast_cut done — 6 segments cut
Chapter rendered: ...
Chapter rendered: ...
Stitch done → /app/shared/volumes/.../podcast_final.mp4
```

---

## Output

Final video is at:
```bash
ls shared/volumes/*/podcast_final.mp4
```

Copy to desktop:
```bash
cp shared/volumes/*/podcast_final.mp4 ~/Desktop/podcast_final.mp4
```

---

## Services Used

| Service | Port | Role |
|---------|------|------|
| transcription | 8001 | Whisper transcription |
| orchestrator | 8007 | LangGraph pipeline runner |
| ffmpeg | 8004 | Video cutting |
| podcast_renderer | 8009 | Chapter cards + captions + stitch |

---

## Troubleshooting

**Pipeline stuck at transcription** — transcription service needs ~30s to be ready after `docker compose up`. Wait and retry.

**0 chapters detected** — check `GROQ_API_KEY` is set in the orchestrator environment.

**Empty chapter files** — timestamps from Groq exceeded video duration. The pipeline now clamps timestamps automatically.

**500 on render_chapter** — check `docker compose logs podcast_renderer` for the actual ffmpeg error.