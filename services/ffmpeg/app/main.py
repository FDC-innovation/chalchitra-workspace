from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import subprocess
import os
import tempfile
import json
import traceback
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chalchitra.ffmpeg")

from app.srt_utils import parse_srt, trim_srt, trim_words, entries_to_ass
from app.renderer import (
    render_intro, render_outro, render_captions_overlay_shorts,
)

app = FastAPI()


class ClipRequest(BaseModel):
    episode_id: str
    file_path: str
    clips: list


class RenderRequest(BaseModel):
    episode_id: str
    clip_path: str
    srt_content: str
    start_seconds: float
    end_seconds: float
    clip_title: str
    show_title: str = "Chalchitra"
    channel_handle: str = "@chalchitra"
    clip_index: int = 0
    intro_duration: float = 3.0
    outro_duration: float = 3.0
    words_json: str = "[]"


def _run(cmd: list, label: str):
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"{label} failed: {e.stderr.decode()}")


def _extract_frame(clip_path: str, output_path: str, position: str = "first"):
    """Extract first or last frame from a video as JPEG."""
    if position == "first":
        cmd = ["ffmpeg", "-y", "-i", clip_path, "-vframes", "1", "-q:v", "2", output_path]
    else:
        cmd = ["ffmpeg", "-y", "-sseof", "-0.5", "-i", clip_path, "-vframes", "1", "-q:v", "2", output_path]
    _run(cmd, f"extract_{position}_frame")




def _burn_captions(input_path: str, ass_path: str, output_path: str):
    _run([
        "ffmpeg", "-y",
        "-i", input_path,
        "-sn",
        "-vf", f"subtitles={ass_path}",
        "-c:v", "libx264", "-c:a", "aac",
        output_path,
    ], "burn_captions")


def _concat_three(intro: str, main: str, outro: str, output_path: str):
    _run([
        "ffmpeg", "-y",
        "-i", intro, "-i", main, "-i", outro,
        "-filter_complex",
        "[0:v][0:a][1:v][1:a][2:v][2:a]concat=n=3:v=1:a=1[v][a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-c:a", "aac",
        output_path,
    ], "concat")


def _make_shorts_raw(input_path: str, output_path: str):
    """Convert any clip to 9:16 1080x1920 blur-pad vertical with SAR 1:1 forced."""
    filter_complex = (
        "[0:v]setsar=1,scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=20:20[bg];"
        "[0:v]setsar=1,scale=1080:-2[fg];"
        "[bg][fg]overlay=x=(W-w)/2:y=(H-h)/2,setsar=1[v]"
    )
    _run([
        "ffmpeg", "-y",
        "-i", input_path,
        "-sn",
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "0:a",
        "-c:v", "libx264", "-c:a", "aac",
        output_path,
    ], "make_shorts_raw")


@app.get("/")
def health():
    return {"status": "ffmpeg service running"}


@app.post("/ffmpeg")
def generate_clips(req: ClipRequest):
    if not os.path.exists(req.file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {req.file_path}")

    output_dir = os.path.dirname(req.file_path)
    generated = []

    for i, clip in enumerate(req.clips):
        start = clip.get("start_seconds", 0)
        end = clip.get("end_seconds", 30)
        title = clip.get("title", f"clip_{i}")
        duration = end - start

        safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in title)[:40]
        output_path = os.path.join(output_dir, f"{req.episode_id}_clip{i}_{safe_title}.mp4")

        cmd = [
            "ffmpeg", "-y",
            "-i", req.file_path,
            "-ss", str(start),
            "-t", str(duration),
            "-c:v", "libx264", "-c:a", "aac",
            "-sn",                          # strip any subtitle streams from source
            "-avoid_negative_ts", "make_zero",
            output_path,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            generated.append({**clip, "file_path": output_path, "status": "done"})
        except subprocess.CalledProcessError as e:
            generated.append({**clip, "status": "failed", "error": e.stderr.decode()})

    return {"episode_id": req.episode_id, "clips": generated}


@app.post("/render")
def render_clip(req: RenderRequest):
    """
    Full render for one clip using Pillow-based animated renderer:
      Landscape (16:9): animated intro + CapCut captions + animated outro
      Shorts    (9:16): blur-pad vertical + CapCut captions + intro/outro
    """
    if not os.path.exists(req.clip_path):
        raise HTTPException(status_code=404, detail=f"Clip not found: {req.clip_path}")

    try:
        return _do_render(req)
    except Exception as e:
        err = traceback.format_exc()
        logger.error(f"[render] failed for clip {req.clip_index}:\n{err}")
        raise HTTPException(status_code=500, detail=str(e))


def _do_render(req: RenderRequest):

    output_dir = os.path.dirname(req.clip_path)
    base = f"{req.episode_id}_clip{req.clip_index}"

    with tempfile.TemporaryDirectory() as tmp:
        intro_frame = os.path.join(tmp, "intro_frame.jpg")
        outro_frame = os.path.join(tmp, "outro_frame.jpg")
        intro_9     = os.path.join(tmp, "intro_9.mp4")
        outro_9     = os.path.join(tmp, "outro_9.mp4")
        shorts_raw  = os.path.join(tmp, "shorts_raw.mp4")
        captioned_9 = os.path.join(tmp, "captioned_9.mp4")

        # ── Word timestamps ────────────────────────────────────────────────
        all_words  = json.loads(req.words_json) if req.words_json else []
        clip_words = trim_words(all_words, req.start_seconds, req.end_seconds)

        # ── Extract first/last frames for intro/outro backgrounds ──────────
        _extract_frame(req.clip_path, intro_frame, "first")
        _extract_frame(req.clip_path, outro_frame, "last")

        # ── Shorts only: blur-pad → intro/outro → captions → concat ─────────
        render_intro(intro_frame, intro_9, channel=req.show_title,
                     clip_title=req.clip_title, duration=req.intro_duration,
                     width=1080, height=1920)
        render_outro(outro_frame, outro_9, handle=req.channel_handle,
                     duration=req.outro_duration, width=1080, height=1920)

        _make_shorts_raw(req.clip_path, shorts_raw)
        if clip_words:
            render_captions_overlay_shorts(clip_words, shorts_raw, captioned_9,
                                           width=1080, height=1920)
        else:
            entries      = parse_srt(req.srt_content)
            clip_entries = trim_srt(entries, req.start_seconds, req.end_seconds)
            ass_path9    = os.path.join(tmp, "fallback9.ass")
            with open(ass_path9, "w", encoding="utf-8") as f:
                f.write(entries_to_ass(clip_entries, 1080, 1920, 160))
            _burn_captions(shorts_raw, ass_path9, captioned_9)

        shorts_path = os.path.join(output_dir, f"{base}_shorts.mp4")
        _concat_three(intro_9, captioned_9, outro_9, shorts_path)
        landscape_path = shorts_path  # return shorts as landscape too for UI compat

    return {
        "episode_id": req.episode_id,
        "clip_index": req.clip_index,
        "landscape_path": landscape_path,
        "shorts_path": shorts_path,
    }
