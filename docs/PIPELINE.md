# Pipeline — Step by Step

This document explains exactly what happens from the moment a video is uploaded to when the final clips are ready.

---

## Trigger

When a video is uploaded via `POST /api/upload/`:

1. File is saved to `shared/volumes/{episode_id}.ext`
2. An `Episode` record is created in SQLite
3. Five `Job` records are created (one per step), all with status `pending`
4. `run_pipeline(episode_id, file_path)` is queued as a background task

---

## Step 1 — Transcribe

**Service:** `transcription` (port 8001)  
**Endpoint:** `POST /transcribe`  
**Timeout:** 10 minutes

**Input:**
```json
{
  "episode_id": "...",
  "file_path": "/app/data/{episode_id}.mp4",
  "task": "translate"
}
```

**What Whisper does:**
- Loads the audio from the video file
- Runs speech recognition with `word_timestamps=True`
- `task="translate"` forces output to English regardless of source language (Hindi, Urdu, etc.)

**Output saved to Episode:**
| Field | Value |
|---|---|
| `transcript` | Full English text of the entire video |
| `duration_sec` | Total video duration in seconds |
| `words_json` | JSON array of `{word, start, end}` with millisecond precision |
| `srt_file` | Path to `/app/data/{episode_id}.srt` |

**Job status:** `transcribe → done`

---

## Step 2 — Enrich

**Service:** `enrich` (port 8002)  
**Endpoint:** `POST /enrich`  
**Model:** Claude claude-sonnet-4-20250514  
**Timeout:** 2 minutes

**Input:**
```json
{
  "episode_id": "...",
  "transcript": "full english transcript text..."
}
```

**What Claude does:**  
Given the transcript, generates structured metadata as JSON:
```json
{
  "title": "From Rich Family to Film at Age 12",
  "show_notes": "2-3 sentence summary...",
  "tags": ["film production", "career", "family", ...],
  "chapters": [
    {"title": "Family Background", "start_time": 0},
    {"title": "Meeting Tony", "start_time": 45}
  ]
}
```

**Output saved to Episode:**
`title`, `show_notes`, `tags` (JSON), `chapters` (JSON)

**Job status:** `enrich → done`

---

## Step 3 — Detect

**Service:** `detect` (port 8003)  
**Endpoint:** `POST /detect`  
**Model:** Claude claude-sonnet-4-20250514  
**Timeout:** 2 minutes

**Input:**
```json
{
  "episode_id": "...",
  "transcript": "...",
  "srt": "full SRT file content..."
}
```

**What Claude does:**  
Analyzes the transcript and finds the 3 best viral clip segments:
```json
[
  {
    "title": "12-Year-Old Gets Film Break",
    "start_seconds": 27.96,
    "end_seconds": 68.44,
    "reason": "Inspiring story about getting discovered at 12..."
  },
  ...
]
```

Clips are typically 30–90 seconds each.

**Output saved to Episode:**  
`detected_clips` (JSON array)

**Job status:** `detect → done`

---

## Step 4 — Cut Clips (FFmpeg)

**Service:** `ffmpeg` (port 8004)  
**Endpoint:** `POST /ffmpeg`  
**Timeout:** 5 minutes

**Input:**
```json
{
  "episode_id": "...",
  "file_path": "/app/data/{episode_id}.mp4",
  "clips": [
    {"title": "...", "start_seconds": 27.96, "end_seconds": 68.44, ...}
  ]
}
```

**What FFmpeg does:**  
For each detected clip, runs:
```
ffmpeg -i source.mp4 -ss {start} -t {duration} -c:v libx264 -c:a aac clip.mp4
```

**Output saved to Episode:**  
`generated_clips` — same array as `detected_clips` but with `file_path` and `status` added to each item.

Files written:
```
{episode_id}_clip0_{safe_title}.mp4
{episode_id}_clip1_{safe_title}.mp4
{episode_id}_clip2_{safe_title}.mp4
```

**Job status:** `ffmpeg → done`

---

## Step 5 — Render

**Service:** `ffmpeg` (port 8004)  
**Endpoint:** `POST /render` (called once per clip)  
**Timeout:** 10 minutes total

**Input per clip:**
```json
{
  "episode_id": "...",
  "clip_path": "/app/data/{episode_id}_clip0_....mp4",
  "srt_content": "full episode SRT...",
  "start_seconds": 27.96,
  "end_seconds": 68.44,
  "clip_title": "12-Year-Old Gets Film Break",
  "show_title": "From Family Legacy to Film Production...",
  "channel_handle": "@chalchitra",
  "clip_index": 0,
  "words_json": "[{word, start, end}, ...]"
}
```

**What happens inside render:**

```
1. Trim words_json to clip time window  →  clip_words[]
2. Generate ASS captions (landscape)    →  captions_landscape.ass
3. Generate ASS captions (shorts)       →  captions_shorts.ass
4. Extract first frame of clip          →  intro_frame.jpg
5. Extract last frame of clip           →  outro_frame.jpg
6. Create 16:9 intro card               →  intro_16.mp4  (blurred frame + channel + title)
7. Create 16:9 outro card               →  outro_16.mp4  (blurred frame + CTA + handle)
8. Create 9:16 intro card               →  intro_9.mp4
9. Create 9:16 outro card               →  outro_9.mp4
10. Burn landscape captions into clip   →  captioned.mp4
11. Concat: intro_16 + captioned + outro_16  →  {base}_landscape.mp4
12. Convert clip to 9:16 blur pad       →  shorts_clip.mp4
13. Concat: intro_9 + shorts_clip + outro_9  →  {base}_shorts.mp4
```

**Caption generation (animated):**
- Words are grouped into lines of max 5 words / max 3 seconds
- Each line is one ASS `Dialogue` entry
- `\kf` tag on each word = yellow karaoke fill highlight as word is spoken
- If `words_json` is empty, falls back to plain SRT-based subtitles

**Output saved to Episode:**  
`polished_clips` — array with `landscape_path` and `shorts_path` added per clip.

**Job status:** `render → done`

---

## Final Output

```
shared/volumes/
├── {episode_id}.mp4                     ← original upload
├── {episode_id}.srt                     ← English subtitles
├── {episode_id}_clip0_{title}.mp4       ← raw cut
├── {episode_id}_clip0_landscape.mp4     ← ✅ final 16:9
├── {episode_id}_clip0_shorts.mp4        ← ✅ final 9:16
├── {episode_id}_clip1_...               ← repeat for clips 1 and 2
└── ...
```

All files are accessible for download at `http://localhost:8000/files/{filename}`.
