from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import subprocess
import os
import tempfile
import json

from app.srt_utils import parse_srt, trim_srt, trim_words, entries_to_ass, words_to_animated_ass

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


def _escape_drawtext(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")


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


def _create_intro(bg_image: str, output_path: str, channel: str, clip_title: str,
                  duration: float, width: int = 1920, height: int = 1080):
    """
    Intro card: blurred frame background with channel name (small, top)
    and clip title (large, center). Whole card fades in/out.
    """
    ch = _escape_drawtext(channel)
    ti = _escape_drawtext(clip_title)

    vf = (
        f"scale={width}:{height},"
        f"boxblur=18:18,"
        f"eq=brightness=-0.25,"
        f"drawtext=fontsize=42:fontcolor=white:bordercolor=black:borderw=2"
        f":text='{ch}':x=(w-text_w)/2:y={int(height*0.38)},"
        f"drawtext=fontsize=76:fontcolor=white:bordercolor=black:borderw=3"
        f":text='{ti}':x=(w-text_w)/2:y={int(height*0.48)},"
        f"fade=t=in:st=0:d=0.4,"
        f"fade=t=out:st={duration-0.4}:d=0.4"
    )
    _run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", bg_image,
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-c:a", "aac",
        "-shortest",
        output_path,
    ], "create_intro")


def _create_outro(bg_image: str, output_path: str, handle: str,
                  duration: float, width: int = 1920, height: int = 1080):
    """
    Outro card: blurred last frame with CTA and social handle.
    """
    ha = _escape_drawtext(handle)

    vf = (
        f"scale={width}:{height},"
        f"boxblur=18:18,"
        f"eq=brightness=-0.25,"
        f"drawtext=fontsize=68:fontcolor=white:bordercolor=black:borderw=3"
        f":text='Follow for more':x=(w-text_w)/2:y={int(height*0.42)},"
        f"drawtext=fontsize=48:fontcolor=#FFD700:bordercolor=black:borderw=2"
        f":text='{ha}':x=(w-text_w)/2:y={int(height*0.55)},"
        f"fade=t=in:st=0:d=0.4,"
        f"fade=t=out:st={duration-0.4}:d=0.4"
    )
    _run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", bg_image,
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-c:a", "aac",
        "-shortest",
        output_path,
    ], "create_outro")


def _burn_captions(input_path: str, ass_path: str, output_path: str):
    _run([
        "ffmpeg", "-y",
        "-i", input_path,
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


def _make_shorts(input_path: str, ass_path: str, output_path: str):
    filter_complex = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=20:20[bg];"
        "[0:v]scale=1080:-2[fg];"
        "[bg][fg]overlay=x=(W-w)/2:y=(H-h)/2[composite];"
        f"[composite]subtitles={ass_path}[v]"
    )
    _run([
        "ffmpeg", "-y",
        "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "0:a",
        "-c:v", "libx264", "-c:a", "aac",
        output_path,
    ], "make_shorts")


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
    Full render for one clip:
      Landscape (16:9): blurred-frame intro + captioned clip + blurred-frame outro
      Shorts    (9:16): blur-pad vertical + animated captions
    """
    if not os.path.exists(req.clip_path):
        raise HTTPException(status_code=404, detail=f"Clip not found: {req.clip_path}")

    output_dir = os.path.dirname(req.clip_path)
    base = f"{req.episode_id}_clip{req.clip_index}"

    with tempfile.TemporaryDirectory() as tmp:
        ass_landscape  = os.path.join(tmp, "captions_landscape.ass")
        ass_shorts     = os.path.join(tmp, "captions_shorts.ass")
        intro_frame    = os.path.join(tmp, "intro_frame.jpg")
        outro_frame    = os.path.join(tmp, "outro_frame.jpg")
        intro_path     = os.path.join(tmp, "intro.mp4")
        outro_path     = os.path.join(tmp, "outro.mp4")
        captioned_path = os.path.join(tmp, "captioned.mp4")

        # ── Animated captions ─────────────────────────────────────────────
        all_words  = json.loads(req.words_json) if req.words_json else []
        clip_words = trim_words(all_words, req.start_seconds, req.end_seconds)

        if clip_words:
            landscape_ass = words_to_animated_ass(clip_words, play_res_x=1920, play_res_y=1080, margin_v=100)
            shorts_ass    = words_to_animated_ass(clip_words, play_res_x=1080, play_res_y=1920, margin_v=180)
        else:
            entries      = parse_srt(req.srt_content)
            clip_entries = trim_srt(entries, req.start_seconds, req.end_seconds)
            landscape_ass = entries_to_ass(clip_entries, play_res_x=1920, play_res_y=1080, margin_v=80)
            shorts_ass    = entries_to_ass(clip_entries, play_res_x=1080, play_res_y=1920, margin_v=160)

        with open(ass_landscape, "w", encoding="utf-8") as f:
            f.write(landscape_ass)
        with open(ass_shorts, "w", encoding="utf-8") as f:
            f.write(shorts_ass)

        # ── Extract frames for blurred backgrounds ────────────────────────
        _extract_frame(req.clip_path, intro_frame, "first")
        _extract_frame(req.clip_path, outro_frame, "last")

        # 16:9 cards
        intro_path_16 = os.path.join(tmp, "intro_16.mp4")
        outro_path_16 = os.path.join(tmp, "outro_16.mp4")
        _create_intro(intro_frame, intro_path_16, channel=req.show_title,
                      clip_title=req.clip_title, duration=req.intro_duration,
                      width=1920, height=1080)
        _create_outro(outro_frame, outro_path_16, handle=req.channel_handle,
                      duration=req.outro_duration, width=1920, height=1080)

        # 9:16 cards
        intro_path_9  = os.path.join(tmp, "intro_9.mp4")
        outro_path_9  = os.path.join(tmp, "outro_9.mp4")
        _create_intro(intro_frame, intro_path_9, channel=req.show_title,
                      clip_title=req.clip_title, duration=req.intro_duration,
                      width=1080, height=1920)
        _create_outro(outro_frame, outro_path_9, handle=req.channel_handle,
                      duration=req.outro_duration, width=1080, height=1920)

        # ── Landscape: captions → concat ──────────────────────────────────
        _burn_captions(req.clip_path, ass_landscape, captioned_path)
        landscape_path = os.path.join(output_dir, f"{base}_landscape.mp4")
        _concat_three(intro_path_16, captioned_path, outro_path_16, landscape_path)

        # ── Shorts: 9:16 blur pad + captions → concat ─────────────────────
        shorts_clip = os.path.join(tmp, "shorts_clip.mp4")
        _make_shorts(req.clip_path, ass_shorts, shorts_clip)
        shorts_path = os.path.join(output_dir, f"{base}_shorts.mp4")
        _concat_three(intro_path_9, shorts_clip, outro_path_9, shorts_path)

    return {
        "episode_id": req.episode_id,
        "clip_index": req.clip_index,
        "landscape_path": landscape_path,
        "shorts_path": shorts_path,
    }
