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
    render_captions_overlay,
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
    hook: str = ""
    caption_position: str = "bottom"
    caption_style: str = "clean"
    show_intro: bool = True
    show_outro: bool = True
    channel_handle: str = "@chalchitra"


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
        "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-c:a", "aac",
        output_path,
    ], "burn_captions")


def _concat_three(intro: str, main: str, outro: str, output_path: str):
    _run([
        "ffmpeg", "-y",
        "-i", intro, "-i", main, "-i", outro,
        "-filter_complex",
        "[0:v][0:a][1:v][1:a][2:v][2:a]concat=n=3:v=1:a=1[v][a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-c:a", "aac",
        output_path,
    ], "concat")


def _make_shorts_raw(input_path: str, output_path: str):
    """Fallback: blur-pad vertical conversion when face tracking fails."""
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
        "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-c:a", "aac",
        output_path,
    ], "make_shorts_raw")


def _make_shorts_face_crop(input_path: str, output_path: str):
    """
    Smart face-tracking crop: detects speaker's face and keeps them
    centered in a 9:16 frame. Falls back to blur-pad if no face found.
    """
    try:
        import cv2
    except ImportError:
        logger.warning("opencv not available, falling back to blur-pad")
        _make_shorts_raw(input_path, output_path)
        return

    OUT_W, OUT_H  = 1080, 1920
    SAMPLE_SEC    = 1.0   # detect face every 1 second (less memory pressure)
    SMOOTH_SEC    = 2.0   # moving average window in seconds
    DETECT_W      = 320   # downscale to this width for detection (low RAM)

    cap   = cv2.VideoCapture(input_path)
    fps   = cap.get(cv2.CAP_PROP_FPS) or 30
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Width of the crop window in source pixels for 9:16 output
    crop_w    = int(src_h * OUT_W / OUT_H)
    crop_w    = min(crop_w, src_w)
    default_x = (src_w - crop_w) // 2

    # Scale factor for mapping detection coords back to source
    detect_scale = src_w / DETECT_W
    detect_h     = int(src_h / detect_scale)

    cascade      = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    sample_every = max(1, int(fps * SAMPLE_SEC))
    raw: dict    = {}
    frame_idx    = 0

    # Pass 1 — detect faces at sample frames (low-res for memory efficiency)
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % sample_every == 0:
            # Shrink frame before detection — uses ~10x less memory
            small = cv2.resize(frame, (DETECT_W, detect_h))
            gray  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.1, 4, minSize=(30, 30))
            if len(faces) > 0:
                fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
                # Scale detection coords back to source resolution
                face_cx = int((fx + fw // 2) * detect_scale)
                cx = max(0, min(face_cx - crop_w // 2, src_w - crop_w))
                raw[frame_idx] = cx
            del small, gray  # explicit free
        frame_idx += 1

    cap.release()
    total = frame_idx

    # Fall back if no face detected in the whole clip
    if not raw:
        logger.info("no face detected, using blur-pad fallback")
        _make_shorts_raw(input_path, output_path)
        return

    # Interpolate raw detections to every frame
    sorted_keys = sorted(raw.keys())
    all_x = [default_x] * total

    # Before first detection — use first value
    for f in range(sorted_keys[0]):
        all_x[f] = raw[sorted_keys[0]]

    # Between detections — linear interpolation
    for i in range(len(sorted_keys) - 1):
        k0, k1 = sorted_keys[i], sorted_keys[i + 1]
        x0, x1 = raw[k0], raw[k1]
        for f in range(k0, k1):
            t = (f - k0) / max(1, k1 - k0)
            all_x[f] = int(x0 + (x1 - x0) * t)

    # After last detection — hold last value
    for f in range(sorted_keys[-1], total):
        all_x[f] = raw[sorted_keys[-1]]

    # Smooth with moving average (prevents jitter)
    half = max(1, int(fps * SMOOTH_SEC / 2))
    smoothed = []
    for i in range(total):
        lo = max(0, i - half); hi = min(total, i + half + 1)
        smoothed.append(int(sum(all_x[lo:hi]) / (hi - lo)))

    # Build FFmpeg crop x expression — piecewise linear at 1-second keyframes
    kf_step  = max(1, int(fps))
    keyframes = list(range(0, total, kf_step))
    if keyframes[-1] != total - 1:
        keyframes.append(total - 1)

    kf_times = [k / fps for k in keyframes]
    kf_vals  = [smoothed[min(k, len(smoothed) - 1)] for k in keyframes]

    # Build nested if() expression: piecewise linear between keyframes
    expr = str(kf_vals[-1])
    for i in range(len(kf_times) - 2, -1, -1):
        t0, t1 = kf_times[i], kf_times[i + 1]
        x0, x1 = kf_vals[i], kf_vals[i + 1]
        dt = max(0.001, t1 - t0)
        if abs(x1 - x0) < 2:
            seg = str(x0)
        else:
            seg = f"({x0}+({x1-x0})*(t-{t0:.2f})/{dt:.2f})"
        expr = f"if(lte(t,{t1:.2f}),{seg},{expr})"

    vf = (
        f"crop=w={crop_w}:h={src_h}:x='{expr}':y=0,"
        f"scale={OUT_W}:{OUT_H}:flags=lanczos,"
        f"setsar=1"
    )

    try:
        _run([
            "ffmpeg", "-y", "-i", input_path, "-sn",
            "-vf", vf,
            "-map", "0:v", "-map", "0:a",
            "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-c:a", "aac",
            output_path,
        ], "make_shorts_face_crop")
    except Exception as e:
        logger.warning(f"face crop failed ({e}), falling back to blur-pad")
        _make_shorts_raw(input_path, output_path)


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
            "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-c:a", "aac",
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

        # ── Render intro/outro if enabled ─────────────────────────────────
        if req.show_intro:
            render_intro(intro_frame, intro_9, channel=req.show_title,
                         clip_title=req.clip_title, duration=req.intro_duration,
                         width=1080, height=1920)
        if req.show_outro:
            render_outro(outro_frame, outro_9, handle=req.channel_handle,
                         duration=req.outro_duration, width=1080, height=1920)

        _make_shorts_face_crop(req.clip_path, shorts_raw)
        if clip_words:
            render_captions_overlay_shorts(clip_words, shorts_raw, captioned_9,
                                           width=1080, height=1920, hook=req.hook,
                                           caption_position=req.caption_position,
                                           caption_style=req.caption_style)
        else:
            entries      = parse_srt(req.srt_content)
            clip_entries = trim_srt(entries, req.start_seconds, req.end_seconds)
            ass_path9    = os.path.join(tmp, "fallback9.ass")
            with open(ass_path9, "w", encoding="utf-8") as f:
                f.write(entries_to_ass(clip_entries, 1080, 1920, 160))
            _burn_captions(shorts_raw, ass_path9, captioned_9)

        shorts_path = os.path.join(output_dir, f"{base}_shorts.mp4")

        # ── Concat based on what's enabled ───────────────────────────────
        if req.show_intro and req.show_outro:
            _concat_three(intro_9, captioned_9, outro_9, shorts_path)
        elif req.show_intro:
            _concat_three(intro_9, captioned_9, captioned_9, shorts_path)
            import shutil; shutil.copy(captioned_9, shorts_path)
            _run(["ffmpeg", "-y", "-i", intro_9, "-i", captioned_9,
                  "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
                  "-map", "[v]", "-map", "[a]",
                  "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-c:a", "aac",
                  shorts_path], "concat_intro_only")
        elif req.show_outro:
            _run(["ffmpeg", "-y", "-i", captioned_9, "-i", outro_9,
                  "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
                  "-map", "[v]", "-map", "[a]",
                  "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-c:a", "aac",
                  shorts_path], "concat_outro_only")
        else:
            import shutil; shutil.copy(captioned_9, shorts_path)
        landscape_path = shorts_path  # return shorts as landscape too for UI compat

    return {
        "episode_id": req.episode_id,
        "clip_index": req.clip_index,
        "landscape_path": landscape_path,
        "shorts_path": shorts_path,
    }
