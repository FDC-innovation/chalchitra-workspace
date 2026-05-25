from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import os
import subprocess
import tempfile
import shutil
from PIL import Image, ImageDraw, ImageFont

app = FastAPI()


class Word(BaseModel):
    word: str
    start: float
    end: float


class RenderRequest(BaseModel):
    episode_id: str
    clip_path: str
    title: str
    start_seconds: float
    end_seconds: float
    words: List[Word] = []
    channel_name: str = "Chalchitra"
    cta_text: str = "Follow for more"


@app.get("/")
def health():
    return {"status": "renderer service running"}


def run_cmd(cmd: list, label: str):
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise Exception(f"{label} failed:\n{result.stderr.decode()}")
    return result


def is_valid_clip(path: str) -> bool:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True)
    val = result.stdout.strip()
    return result.returncode == 0 and val not in ("", "N/A")


def get_clip_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def find_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansBold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def reframe_to_9x16(input_path: str, output_path: str):
    vf = (
        "scale=1080:-2:flags=lanczos,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,"
        "format=yuv420p"
    )
    run_cmd([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", vf,
        "-r", "30",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-profile:v", "baseline", "-level", "3.0",
        "-c:a", "aac", "-ar", "44100",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        output_path
    ], "Reframe")


def make_intro_card(title: str, width: int, height: int,
                    fps: int, duration: float, output_path: str):
    font_large = find_font(96)
    total_frames = int(duration * fps)
    frame_dir = tempfile.mkdtemp(prefix="intro_")

    words = title.split()
    lines = []
    for i in range(0, len(words), 2):
        lines.append(" ".join(words[i:i+2]))

    try:
        for frame_idx in range(total_frames):
            t = frame_idx / fps
            if t < 0.3:
                alpha = int(255 * t / 0.3)
            elif t > duration - 0.3:
                alpha = int(255 * (duration - t) / 0.3)
            else:
                alpha = 255
            alpha = max(0, min(255, alpha))

            img = Image.new("RGB", (width, height), (0, 0, 0))
            draw = ImageDraw.Draw(img)

            line_height = 110
            total_text_h = len(lines) * line_height
            start_y = (height - total_text_h) // 2

            for i, line in enumerate(lines):
                bbox = draw.textbbox((0, 0), line, font=font_large)
                lw = bbox[2] - bbox[0]
                x = (width - lw) // 2
                y = start_y + i * line_height

                color_r = int(255 * alpha / 255)
                color_g = int((230 if i == 0 else 255) * alpha / 255)
                color_b = int((0 if i == 0 else 255) * alpha / 255)

                draw.text((x+4, y+4), line, font=font_large, fill=(0, 0, 0))
                draw.text((x, y), line, font=font_large,
                          fill=(color_r, color_g, color_b))

            img.save(os.path.join(frame_dir, f"frame_{frame_idx:06d}.png"), "PNG")

        run_cmd([
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", os.path.join(frame_dir, "frame_%06d.png"),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-profile:v", "baseline", "-level", "3.0",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            output_path
        ], "Intro card encode")
    finally:
        shutil.rmtree(frame_dir, ignore_errors=True)


def make_outro_card(channel_name: str, cta_text: str,
                    width: int, height: int,
                    fps: int, duration: float, output_path: str):
    font_channel = find_font(100)
    font_cta = find_font(56)
    total_frames = int(duration * fps)
    frame_dir = tempfile.mkdtemp(prefix="outro_")

    try:
        for frame_idx in range(total_frames):
            t = frame_idx / fps
            if t < 0.4:
                alpha = int(255 * t / 0.4)
            elif t > duration - 0.3:
                alpha = int(255 * (duration - t) / 0.3)
            else:
                alpha = 255
            alpha = max(0, min(255, alpha))

            img = Image.new("RGB", (width, height), (0, 0, 0))
            draw = ImageDraw.Draw(img)

            cb = draw.textbbox((0, 0), channel_name, font=font_channel)
            cw = cb[2] - cb[0]
            ch = cb[3] - cb[1]
            cx = (width - cw) // 2
            cy = height // 2 - ch - 30

            draw.text((cx+4, cy+4), channel_name, font=font_channel, fill=(0, 0, 0))
            draw.text((cx, cy), channel_name, font=font_channel,
                      fill=(int(255*alpha/255), int(230*alpha/255), 0))

            line_y = height // 2 + 10
            draw.rectangle([width//4, line_y, 3*width//4, line_y+3],
                           fill=(255, 255, 255))

            ctb = draw.textbbox((0, 0), cta_text, font=font_cta)
            ctw = ctb[2] - ctb[0]
            ctx = (width - ctw) // 2
            cty = height // 2 + 40

            draw.text((ctx+3, cty+3), cta_text, font=font_cta, fill=(0, 0, 0))
            draw.text((ctx, cty), cta_text, font=font_cta,
                      fill=(int(255*alpha/255), int(255*alpha/255), int(255*alpha/255)))

            img.save(os.path.join(frame_dir, f"frame_{frame_idx:06d}.png"), "PNG")

        run_cmd([
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", os.path.join(frame_dir, "frame_%06d.png"),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-profile:v", "baseline", "-level", "3.0",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            output_path
        ], "Outro card encode")
    finally:
        shutil.rmtree(frame_dir, ignore_errors=True)


def draw_word_frame(word_text: str, width: int, height: int,
                    font: ImageFont.FreeTypeFont) -> Image.Image:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    text = word_text.upper()
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    x = (width - tw) // 2
    y = height - 420
    stroke = 6
    for dx in range(-stroke, stroke + 1, 2):
        for dy in range(-stroke, stroke + 1, 2):
            if dx != 0 or dy != 0:
                draw.text((x+dx, y+dy), text, font=font, fill=(0, 0, 0, 255))
    draw.text((x, y), text, font=font, fill=(255, 230, 0, 255))
    return img


def render_caption_frames(
    words: List[Word], start_offset: float, duration: float,
    width: int, height: int, fps: int, frame_dir: str,
) -> bool:
    clip_words = [
        Word(word=w.word,
             start=round(w.start - start_offset, 3),
             end=round(w.end - start_offset, 3))
        for w in words
        if w.end > start_offset and w.start < start_offset + duration + 1.0
    ]
    if not clip_words:
        return False

    font = find_font(110)
    total_frames = int(duration * fps)

    for frame_idx in range(total_frames):
        t = frame_idx / fps
        active_word = next(
            (w.word for w in clip_words if w.start <= t < w.end), None)
        img = (draw_word_frame(active_word, width, height, font)
               if active_word
               else Image.new("RGBA", (width, height), (0, 0, 0, 0)))
        img.save(os.path.join(frame_dir, f"frame_{frame_idx:06d}.png"), "PNG")

    return True


def burn_captions_onto_video(
    base_video: str, frame_dir: str,
    fps: int, duration: float, output_path: str,
):
    run_cmd([
        "ffmpeg", "-y",
        "-i", base_video,
        "-framerate", str(fps),
        "-i", os.path.join(frame_dir, "frame_%06d.png"),
        "-filter_complex",
        "[0:v]format=yuv420p[base];[1:v]format=yuva420p[ov];[base][ov]overlay=0:0,format=yuv420p",
        "-map", "0:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-profile:v", "baseline", "-level", "3.0",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-t", str(duration),
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        output_path
    ], "Burn captions")


def concat_videos(intro: str, main: str, outro: str,
                  output_path: str, tmp_dir: str):
    list_file = os.path.join(tmp_dir, "concat.txt")
    with open(list_file, "w") as f:
        f.write(f"file '{intro}'\n")
        f.write(f"file '{main}'\n")
        f.write(f"file '{outro}'\n")

    run_cmd([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-profile:v", "baseline", "-level", "3.0",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        output_path
    ], "Concat")


@app.post("/render")
def render_clip(req: RenderRequest):
    if not os.path.exists(req.clip_path):
        raise HTTPException(status_code=404, detail=f"Clip not found: {req.clip_path}")
    if not is_valid_clip(req.clip_path):
        raise HTTPException(status_code=400, detail=f"Clip not seekable: {req.clip_path}")

    safe_title = "".join(
        c if c.isalnum() or c in "-_" else "_" for c in req.title)[:40]
    episode_dir = os.path.join("/app/shared/volumes", req.episode_id)
    os.makedirs(episode_dir, exist_ok=True)

    duration = get_clip_duration(req.clip_path)
    if duration <= 0:
        raise HTTPException(status_code=400,
                            detail=f"Could not read duration: {req.clip_path}")

    steps_done = []
    tmp_dir = tempfile.mkdtemp(prefix="render_tmp_")
    FPS = 30
    W, H = 1080, 1920

    try:
        reframed = os.path.join(tmp_dir, "reframed.mp4")
        reframe_to_9x16(req.clip_path, reframed)
        steps_done.append("reframe")

        captioned = os.path.join(tmp_dir, "captioned.mp4")
        if req.words:
            frame_dir = os.path.join(tmp_dir, "cap_frames")
            os.makedirs(frame_dir)
            has_words = render_caption_frames(
                words=req.words, start_offset=req.start_seconds,
                duration=duration, width=W, height=H,
                fps=FPS, frame_dir=frame_dir,
            )
            if has_words:
                burn_captions_onto_video(reframed, frame_dir, FPS, duration, captioned)
                steps_done.append("captions")
            else:
                shutil.copy2(reframed, captioned)
        else:
            shutil.copy2(reframed, captioned)

        intro_card = os.path.join(tmp_dir, "intro.mp4")
        make_intro_card(req.title, W, H, FPS, 2.0, intro_card)

        intro_with_audio = os.path.join(tmp_dir, "intro_audio.mp4")
        run_cmd([
            "ffmpeg", "-y",
            "-i", intro_card,
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            "-movflags", "+faststart",
            intro_with_audio
        ], "Intro audio")

        outro_card = os.path.join(tmp_dir, "outro.mp4")
        make_outro_card(req.channel_name, req.cta_text, W, H, FPS, 3.0, outro_card)

        outro_with_audio = os.path.join(tmp_dir, "outro_audio.mp4")
        run_cmd([
            "ffmpeg", "-y",
            "-i", outro_card,
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            "-movflags", "+faststart",
            outro_with_audio
        ], "Outro audio")

        steps_done.append("cards")

        final = os.path.join(episode_dir, safe_title + "_final.mp4")
        concat_videos(intro_with_audio, captioned, outro_with_audio, final, tmp_dir)
        steps_done.append("concat")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        "episode_id": req.episode_id,
        "title": req.title,
        "original_clip": req.clip_path,
        "rendered_clip": final,
        "steps": steps_done,
        "duration_seconds": duration,
        "status": "done"
    }