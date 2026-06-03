"""
podcast_renderer — service on port 8009

POST /render_chapter   → chapter card (fade-in title/subtitle over blurred first frame)
                          + SRT caption burn → returns rendered_path
POST /stitch           → concat all rendered chapter files → final podcast MP4
GET  /                 → health
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import os
import subprocess
import tempfile
import shutil

app = FastAPI()

SHARED = "/app/shared/volumes"
FPS = 30
CARD_DURATION = 3.5      # seconds the chapter title card shows


# ─────────────────────────── helpers ────────────────────────────────────────

def run(cmd: list, label: str):
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed:\n{result.stderr.decode()}")
    return result


def probe_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def find_font(size: int) -> str:
    """Return path to a bold Latin font."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return ""   # ffmpeg will use its built-in fallback


def safe_name(text: str, max_len: int = 40) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in text)[:max_len]


# ─────────────────────────── chapter card ────────────────────────────────────

def make_chapter_card(
    source_video: str,
    title: str,
    subtitle: str,
    duration: float,
    output_path: str,
):
    """
    Grab the first frame of `source_video`, blur it heavily, then
    fade-in title + subtitle text over it using FFmpeg drawtext.
    No Pillow frame loops — pure FFmpeg filter graph, fast.
    """
    font_path = find_font(0)

    # ── escape apostrophes for ffmpeg drawtext ────────────────────────────
    def esc(t: str) -> str:
        return t.replace("'", "\u2019").replace(":", r"\:")

    title_esc = esc(title)
    subtitle_esc = esc(subtitle)

    # fade alpha: alpha=if(lt(t,0.4),t/0.4,if(gt(t,dur-0.3),(dur-t)/0.3,1))
    fade = f"if(lt(t,0.4),t/0.4,if(gt(t,{duration:.2f}-0.3),({duration:.2f}-t)/0.3,1))"

    font_opt = f":fontfile={font_path}" if font_path else ""

    vf = (
        # 1. take only the first frame and loop it for card duration
        "loop=loop=-1:size=1:start=0,"
        # 2. scale to 16:9 1280×720 (podcast, not 9:16)
        "scale=1280:720:force_original_aspect_ratio=increase,"
        "crop=1280:720,"
        # 3. heavy blur for background
        "gblur=sigma=30,"
        # 4. dim overlay (semi-transparent dark wash)
        "colorchannelmixer=rr=0.4:gg=0.4:bb=0.4,"
        # 5. title text — large, centred, white with drop shadow, fade in/out
        f"drawtext=text='{title_esc}'{font_opt}"
        f":fontsize=72:fontcolor=white@1.0"
        f":x=(w-text_w)/2:y=(h-text_h)/2-60"
        f":shadowcolor=black@0.7:shadowx=3:shadowy=3"
        f":alpha='{fade}',"
        # 6. subtitle text — smaller, yellow, below title
        f"drawtext=text='{subtitle_esc}'{font_opt}"
        f":fontsize=36:fontcolor=FFE600@1.0"
        f":x=(w-text_w)/2:y=(h-text_h)/2+40"
        f":shadowcolor=black@0.7:shadowx=2:shadowy=2"
        f":alpha='{fade}'"
    )

    run([
        "ffmpeg", "-y",
        "-ss", "0",
        "-i", source_video,
        "-vf", vf,
        "-t", str(duration),
        "-r", str(FPS),
        "-an",                          # no audio on card
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-profile:v", "baseline", "-level", "3.0",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output_path,
    ], "Chapter card")


def add_silent_audio(video_path: str, output_path: str):
    """Add silent audio track so card can be concatenated with audio clips."""
    run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-c:v", "copy", "-c:a", "aac", "-shortest",
        "-movflags", "+faststart",
        output_path,
    ], "Add silent audio")


# ─────────────────────────── caption burn ────────────────────────────────────

class Word(BaseModel):
    word: str
    start: float
    end: float


def words_to_srt(words: List[Word], start_offset: float, clip_duration: float) -> str:
    """
    Convert word-level timestamps to SRT, adjusted to clip-local time.
    Groups words into ~5-word subtitle lines.
    """
    clip_words = [
        w for w in words
        if w.end > start_offset and w.start < start_offset + clip_duration + 1.0
    ]
    if not clip_words:
        return ""

    def fmt(t: float) -> str:
        t = max(0.0, t)
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        ms = int((t % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = []
    group: List[Word] = []
    idx = 1

    for w in clip_words:
        group.append(w)
        if len(group) >= 5:
            s = group[0].start - start_offset
            e = group[-1].end - start_offset
            text = " ".join(g.word for g in group)
            lines.append(f"{idx}\n{fmt(s)} --> {fmt(e)}\n{text}\n")
            idx += 1
            group = []

    if group:
        s = group[0].start - start_offset
        e = group[-1].end - start_offset
        text = " ".join(g.word for g in group)
        lines.append(f"{idx}\n{fmt(s)} --> {fmt(e)}\n{text}\n")

    return "\n".join(lines)


def burn_srt(video_path: str, srt_path: str, output_path: str):
    font_path = find_font(0)
    font_opt = f":fontfile={font_path}" if font_path else ""
    # subtitles filter with styling
    subtitle_filter = (
        f"subtitles={srt_path}"
        f":force_style='FontSize=28,PrimaryColour=&H00FFFF00,"   # yellow
        f"OutlineColour=&H00000000,Outline=2,Bold=1,"
        f"Alignment=2,MarginV=40'"                               # bottom centre
    )
    run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", subtitle_filter,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-profile:v", "baseline", "-level", "3.0",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        output_path,
    ], "Burn SRT")


# ─────────────────────────── concat ──────────────────────────────────────────

def concat_files(paths: List[str], output_path: str, tmp_dir: str):
    list_file = os.path.join(tmp_dir, "concat.txt")
    with open(list_file, "w") as f:
        for p in paths:
            f.write(f"file '{p}'\n")

    run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-profile:v", "baseline", "-level", "3.0",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        output_path,
    ], "Concat chapters")


# ─────────────────────────── request models ──────────────────────────────────

class RenderChapterRequest(BaseModel):
    episode_id: str
    clip_path: str
    title: str
    subtitle: str = ""
    start_seconds: float
    end_seconds: float
    words: List[Word] = []
    chapter_index: int = 0


class StitchRequest(BaseModel):
    episode_id: str
    chapter_paths: List[str]


# ─────────────────────────── routes ──────────────────────────────────────────

@app.get("/")
def health():
    return {"status": "podcast_renderer running"}


@app.post("/render_chapter")
def render_chapter(req: RenderChapterRequest):
    if not os.path.exists(req.clip_path):
        raise HTTPException(status_code=404, detail=f"Clip not found: {req.clip_path}")

    duration = probe_duration(req.clip_path)
    if duration <= 0:
        raise HTTPException(status_code=400, detail=f"Cannot read duration: {req.clip_path}")

    episode_dir = os.path.join(SHARED, req.episode_id)
    os.makedirs(episode_dir, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="pod_render_")
    safe_title = safe_name(req.title)

    try:
        # 1. Chapter title card (blurred first frame + fade-in text)
        card_raw = os.path.join(tmp_dir, "card_raw.mp4")
        make_chapter_card(
            source_video=req.clip_path,
            title=req.title,
            subtitle=req.subtitle,
            duration=CARD_DURATION,
            output_path=card_raw,
        )

        card_audio = os.path.join(tmp_dir, "card_audio.mp4")
        add_silent_audio(card_raw, card_audio)

        # 2. Burn captions onto the chapter clip body
        captioned_clip = os.path.join(tmp_dir, "captioned.mp4")
        if req.words:
            srt_text = words_to_srt(req.words, req.start_seconds, duration)
            if srt_text.strip():
                srt_path = os.path.join(tmp_dir, "chapter.srt")
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(srt_text)
                burn_srt(req.clip_path, srt_path, captioned_clip)
            else:
                shutil.copy2(req.clip_path, captioned_clip)
        else:
            shutil.copy2(req.clip_path, captioned_clip)

        # 3. Join card + captioned clip for this chapter
        chapter_out = os.path.join(
            episode_dir,
            f"chapter_{req.chapter_index:02d}_{safe_title}.mp4"
        )
        concat_files([card_audio, captioned_clip], chapter_out, tmp_dir)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        "episode_id": req.episode_id,
        "chapter_index": req.chapter_index,
        "title": req.title,
        "rendered_path": chapter_out,
        "duration_seconds": duration + CARD_DURATION,
        "status": "done",
    }


@app.post("/stitch")
def stitch_chapters(req: StitchRequest):
    missing = [p for p in req.chapter_paths if not os.path.exists(p)]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing files: {missing}")

    episode_dir = os.path.join(SHARED, req.episode_id)
    os.makedirs(episode_dir, exist_ok=True)
    final_path = os.path.join(episode_dir, "podcast_final.mp4")
    tmp_dir = tempfile.mkdtemp(prefix="pod_stitch_")

    try:
        concat_files(req.chapter_paths, final_path, tmp_dir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        "episode_id": req.episode_id,
        "final_video": final_path,
        "chapters_stitched": len(req.chapter_paths),
        "status": "done",
    }