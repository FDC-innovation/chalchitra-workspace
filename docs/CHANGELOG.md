# Changelog

All changes are listed in chronological order with the reason, the files affected, and what was done.

---

## 1. Replaced Remotion with FFmpeg Render Engine

**Why:** Remotion requires a commercial license for production use. The Remotion service directory did not exist — it was only a stub route. Replaced entirely with a free FFmpeg-based solution.

**Files changed:**

| File                                 | Change                                                                         |
| ------------------------------------ | ------------------------------------------------------------------------------ |
| `services/ffmpeg/app/srt_utils.py`   | **New file.** SRT parsing, timestamp trimming, ASS subtitle generation         |
| `services/ffmpeg/app/main.py`        | Added `POST /render` endpoint. Produces landscape + shorts output per clip     |
| `gateway/app/api/routes/remotion.py` | Repurposed from empty stub to render orchestration route                       |
| `gateway/app/core/config.py`         | Renamed `ENABLE_REMOTION` → `ENABLE_RENDER = True`                             |
| `gateway/app/main.py`                | Changed router prefix from `/api/remotion` to `/api/render`, tag to `"Render"` |

**What the render step produces:**

- `_landscape.mp4` — 16:9 with intro card + burned captions + outro card
- `_shorts.mp4` — 9:16 vertical with blur-pad background + captions

---

## 2. Built Direct Pipeline Runner (Replaced n8n)

**Why:** n8n had no workflow configured — it was a blank instance. The pipeline never actually ran after upload. Built a direct Python async pipeline in the gateway that chains all 5 services without any external tool.

**Files changed:**

| File                               | Change                                                                            |
| ---------------------------------- | --------------------------------------------------------------------------------- |
| `gateway/app/services/pipeline.py` | **New file.** Full async pipeline: transcribe → enrich → detect → ffmpeg → render |
| `gateway/app/api/routes/upload.py` | Replaced `trigger_n8n()` with `background_tasks.add_task(run_pipeline, ...)`      |
| `gateway/app/api/routes/steps.py`  | Added `POST /api/steps/run/{episode_id}` to manually re-trigger pipeline          |
| `gateway/app/api/routes/upload.py` | Added `"render"` job to the list created on upload                                |

**Pipeline flow:**

```
Upload → run_pipeline() runs in background
  Step 1: POST /transcribe  → saves transcript, words_json, srt_file
  Step 2: POST /enrich      → saves title, show_notes, tags, chapters
  Step 3: POST /detect      → saves detected_clips
  Step 4: POST /ffmpeg      → saves generated_clips (cut video files)
  Step 5: POST /render      → saves polished_clips (landscape + shorts)
Each step updates Job.status in the database in real time.
```

---

## 3. Fixed Language — English Output

**Why:** Whisper was auto-detecting the source language as Urdu/Hindi and outputting in Arabic script. Captions were unreadable for non-Urdu audiences.

**Files changed:**

| File                                 | Change                                                                                                                                                                                          |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `services/transcription/app/main.py` | Added `task` field (default `"translate"`) and optional `language` field to `TranscribeRequest`. Passes `task="translate"` to Whisper so output is always English regardless of source language |
| `gateway/app/services/pipeline.py`   | Passes `"task": "translate"` in the transcription request                                                                                                                                       |

---

## 4. Animated Word-by-Word Captions (CapCut Style)

**Why:** Original captions were plain subtitle blocks with no animation. Wanted yellow word-by-word karaoke-style highlighting matching industry tools.

**Files changed:**

| File                               | Change                                                                                                                                                                                                        |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `services/ffmpeg/app/srt_utils.py` | Added `trim_words()` to filter word timestamps to a clip window. Added `words_to_animated_ass()` — groups words into lines of 5, uses ASS `\kf` karaoke tags to highlight each word in yellow as it is spoken |
| `services/ffmpeg/app/main.py`      | Added `words_json` field to `RenderRequest`. In `/render`, if word timestamps are available, uses `words_to_animated_ass()` instead of plain SRT subtitles                                                    |
| `gateway/app/services/pipeline.py` | Passes `episode.words_json` to the render request                                                                                                                                                             |

**Caption style:**

- Font: Arial, size 64
- Base colour: white
- Highlight colour: yellow (`&H0000FFFF&`)
- Animation: `\kf` smooth karaoke fill
- Groups: max 5 words per line, max 3 seconds per line
- Fade: 80ms in/out per line

---

## 5. Blurred Frame Intro & Outro Cards

**Why:** Previous intro/outro used a plain black background which looked unprofessional.

**Files changed:**

| File                          | Change                                                                                                                                                                                         |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `services/ffmpeg/app/main.py` | Replaced `_create_card()` with `_create_intro()` and `_create_outro()`. Added `_extract_frame()` to pull first/last frame from the clip. Cards now use blurred+dimmed clip frame as background |

**Intro layout (3 seconds):**

```
░░░░░░ blurred first frame (boxblur=18, brightness=-0.25) ░░░░░░
                     Chalchitra              ← channel name, small
              Big Bold Clip Title            ← clip title, large
```

**Outro layout (3 seconds):**

```
░░░░░░ blurred last frame (boxblur=18, brightness=-0.25) ░░░░░░
                  Follow for more           ← white, large
                   @chalchitra              ← gold (#FFD700), medium
```

**Bug fixed:** Original code used `alpha='if(lt(t,0.4),...)'` in drawtext which caused `No such filter: '0.4)'` because FFmpeg was treating commas inside the expression as filter separators. Fixed by replacing with FFmpeg's `fade=t=in` / `fade=t=out` video filters instead.

---

## 6. Shorts Now Has Intro & Outro

**Why:** Shorts output was only the blur-pad clip with captions — no intro or outro.

**Files changed:**

| File                          | Change                                                                                                                                                                   |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `services/ffmpeg/app/main.py` | In `/render`, now creates separate 9:16 (1080×1920) intro and outro cards, converts clip to 9:16 with blur pad + captions, then concatenates intro + shorts_clip + outro |

---

## 7. Dashboard UI

**Why:** All testing was done through Swagger which is not suitable for demos or team use.

**Files changed:**

| File                            | Change                                                                                                                                                                                                    |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `gateway/app/static/index.html` | **New file.** Full single-page dashboard. Drag & drop upload, live 5-step pipeline progress (polls every 3s), clip cards with landscape + shorts download buttons. Episode history stored in localStorage |
| `gateway/app/main.py`           | Mounts `GET /` → serves `index.html`. Mounts `/files/` → serves output videos for download                                                                                                                |
| `gateway/requirements.txt`      | Added `aiofiles` (required for `StaticFiles`)                                                                                                                                                             |

---

## 8. Removed n8n and Ollama

**Why:** n8n is unused (pipeline runs directly). Ollama (local LLM) is unused (all LLM calls go through Anthropic Claude API directly).

**Files changed:**

| File                 | Change                                                                                                                                      |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `docker-compose.yml` | Removed `n8n` service, `ollama` service, `n8n_data` volume, `N8N_WEBHOOK_URL` and `OLLAMA_URL` env vars, `ollama` from gateway `depends_on` |
