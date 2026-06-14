from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import subprocess
import os
import tempfile
import shutil

app = FastAPI()

SHARED = "/app/shared/volumes"
FPS = 30


def run(cmd: list, label: str):
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed:\n{result.stderr.decode()[-800:]}")
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


def find_font() -> str:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    return next((f for f in candidates if os.path.exists(f)), "")


class Section(BaseModel):
    section_id: int
    title: str
    audio_path: str
    srt_path: Optional[str] = None
    broll_path: Optional[str] = None
    duration_seconds: float
    avatar_image: Optional[str] = None


class RenderRequest(BaseModel):
    episode_id: str
    sections: List[Section]
    avatar_image: Optional[str] = None
    output_title: Optional[str] = "Explainer"


class StitchRequest(BaseModel):
    episode_id: str
    section_paths: List[str]
    output_title: Optional[str] = "explainer_final"


def make_avatar_video(avatar_img: str, audio_path: str, output_path: str, title: str):
    duration = probe_duration(audio_path)
    if duration <= 0:
        raise RuntimeError(f"Cannot read audio duration: {audio_path}")

    font_path = find_font()
    font_opt = f":fontfile={font_path}" if font_path else ""

    def esc(t):
        return t.replace("'", "\u2019").replace(":", r"\:")

    vf = (
        f"scale=1280:720:force_original_aspect_ratio=increase,"
        f"crop=1280:720,"
        f"zoompan=z='min(zoom+0.0008,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={int(duration * FPS)}:s=1280x720:fps={FPS},"
        f"format=yuv420p,"
        f"drawtext=text='{esc(title)}'{font_opt}"
        f":fontsize=36:fontcolor=white@0.9"
        f":x=40:y=h-80"
        f":shadowcolor=black@0.8:shadowx=2:shadowy=2"
        f":box=1:boxcolor=black@0.4:boxborderw=8"
    )

    run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", avatar_img,
        "-i", audio_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "44100",
        "-shortest",
        "-movflags", "+faststart",
        output_path,
    ], "Avatar Ken Burns")


def make_broll_video(broll_path: str, audio_path: str, srt_path: Optional[str],
                     output_path: str, tmp_dir: str):
    audio_dur = probe_duration(audio_path)
    broll_dur = probe_duration(broll_path)

    if audio_dur <= 0:
        raise RuntimeError(f"Cannot read audio duration: {audio_path}")
    if broll_dur <= 0:
        raise RuntimeError(f"Cannot read broll duration: {broll_path}")

    scaled = os.path.join(tmp_dir, "broll_scaled.mp4")

    # If broll is shorter than audio, loop it
    if broll_dur < audio_dur:
        loop_count = int(audio_dur / broll_dur) + 2
        run([
            "ffmpeg", "-y",
            "-stream_loop", str(loop_count),
            "-i", broll_path,
            "-t", str(audio_dur),
            "-vf", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,format=yuv420p",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-an",
            scaled,
        ], "Scale and loop broll")
    else:
        run([
            "ffmpeg", "-y",
            "-i", broll_path,
            "-t", str(audio_dur),
            "-vf", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,format=yuv420p",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-an",
            scaled,
        ], "Scale broll")

    # Merge with audio — explicitly set duration to audio length
    merged = os.path.join(tmp_dir, "broll_merged.mp4")
    run([
        "ffmpeg", "-y",
        "-i", scaled,
        "-i", audio_path,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "44100",
        "-t", str(audio_dur),
        merged,
    ], "Merge broll audio")

    # Burn captions if SRT exists and is non-empty
    if srt_path and os.path.exists(srt_path) and os.path.getsize(srt_path) > 10:
        font_path = find_font()
        font_opt = f":fontfile={font_path}" if font_path else ""
        run([
            "ffmpeg", "-y",
            "-i", merged,
            "-vf", (
                f"subtitles={srt_path}"
                f":force_style='FontSize=28,PrimaryColour=&H00FFFFFF,"
                f"OutlineColour=&H00000000,Outline=2,Bold=1,"
                f"Alignment=2,MarginV=40'"
            ),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-movflags", "+faststart",
            output_path,
        ], "Burn captions")
    else:
        shutil.copy2(merged, output_path)


@app.get("/")
def health():
    return {"status": "explainer_renderer running"}


@app.post("/render_section")
def render_section(req: RenderRequest):
    episode_dir = os.path.join(SHARED, req.episode_id)
    os.makedirs(episode_dir, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="explainer_")
    rendered = []
    failed = []

    avatar_img = req.avatar_image or os.path.join(SHARED, "avatar.jpg")

    try:
        for section in req.sections:
            out_path = os.path.join(
                episode_dir,
                f"section_{section.section_id:02d}_rendered.mp4"
            )
            try:
                has_broll = (
                    section.broll_path and
                    os.path.exists(section.broll_path) and
                    os.path.getsize(section.broll_path) > 1000
                )
                has_avatar = avatar_img and os.path.exists(avatar_img)

                if has_broll:
                    make_broll_video(
                        broll_path=section.broll_path,
                        audio_path=section.audio_path,
                        srt_path=section.srt_path,
                        output_path=out_path,
                        tmp_dir=tmp_dir,
                    )
                elif has_avatar:
                    make_avatar_video(
                        avatar_img=section.avatar_image or avatar_img,
                        audio_path=section.audio_path,
                        output_path=out_path,
                        title=section.title,
                    )
                else:
                    # Fallback: audio only with black background
                    run([
                        "ffmpeg", "-y",
                        "-f", "lavfi", "-i", f"color=c=black:s=1280x720:r={FPS}",
                        "-i", section.audio_path,
                        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                        "-pix_fmt", "yuv420p",
                        "-c:a", "aac",
                        "-shortest",
                        "-movflags", "+faststart",
                        out_path,
                    ], "Black background fallback")

                rendered.append({
                    "section_id": section.section_id,
                    "title": section.title,
                    "rendered_path": out_path,
                    "duration_seconds": probe_duration(out_path),
                })
            except Exception as e:
                failed.append({"section_id": section.section_id, "error": str(e)})
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        "episode_id": req.episode_id,
        "rendered": rendered,
        "failed": failed,
    }


@app.post("/stitch")
def stitch(req: StitchRequest):
    episode_dir = os.path.join(SHARED, req.episode_id)
    os.makedirs(episode_dir, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="stitch_")

    missing = [p for p in req.section_paths if not os.path.exists(p)]
    if missing:
        raise HTTPException(400, f"Missing files: {missing}")

    safe_title = "".join(
        c if c.isalnum() or c in "-_" else "_"
        for c in (req.output_title or "explainer")
    )[:50]
    final_path = os.path.join(episode_dir, f"{safe_title}.mp4")
    list_file = os.path.join(tmp_dir, "concat.txt")

    with open(list_file, "w") as f:
        for p in req.section_paths:
            f.write(f"file '{p}'\n")

    try:
        run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-movflags", "+faststart",
            final_path,
        ], "Stitch sections")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        "episode_id": req.episode_id,
        "final_video": final_path,
        "sections_stitched": len(req.section_paths),
    }