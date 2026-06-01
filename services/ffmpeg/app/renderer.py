"""
Chalchitra Visual Renderer
Pillow + numpy based frame-by-frame animation engine.
Streams frames directly to FFmpeg — no full-video RAM usage.
"""
import os
import re
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from typing import List, Dict, Tuple, Optional

try:
    import cv2 as _cv2
    _CV2_OK = True
except ImportError:
    _CV2_OK = False

FPS = 15

ORANGE   = (255, 140,   0)
WHITE    = (255, 255, 255)
BLACK    = (  0,   0,   0)
GOLD     = (255, 200,   0)
DARK_BOX = ( 15,  15,  15)
CORAL    = (255,  80,  60)
CYAN     = ( 80, 220, 255)


# ── Face region detection ─────────────────────────────────────────────────────
def _detect_face_region(clip_path: str, height: int) -> float:
    """
    Sample a few frames, detect the face, return average face-center Y
    as a fraction of frame height (0.0 = top, 1.0 = bottom).
    Returns 0.5 if detection fails.
    """
    if not _CV2_OK:
        return 0.5
    try:
        cap     = _cv2.VideoCapture(clip_path)
        fps     = cap.get(_cv2.CAP_PROP_FPS) or 30
        src_h   = int(cap.get(_cv2.CAP_PROP_FRAME_HEIGHT))
        cascade = _cv2.CascadeClassifier(
            _cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        DETECT_W     = 320
        detect_scale = src_h / DETECT_W if DETECT_W < src_h else 1.0
        detect_h     = int(src_h / detect_scale)
        sample_every = max(1, int(fps * 2))
        face_ys: List[float] = []
        frame_idx = 0

        while len(face_ys) < 6:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_idx % sample_every == 0:
                small = _cv2.resize(frame, (DETECT_W, detect_h))
                gray  = _cv2.cvtColor(small, _cv2.COLOR_BGR2GRAY)
                faces = cascade.detectMultiScale(gray, 1.1, 4, minSize=(30, 30))
                if len(faces) > 0:
                    fx, fy, fw, fh = max(faces, key=lambda f: f[2]*f[3])
                    face_ys.append((fy + fh / 2) / detect_h)
                del small, gray
            frame_idx += 1
        cap.release()
        return sum(face_ys) / len(face_ys) if face_ys else 0.5
    except Exception:
        return 0.5


# ── Hook parser ───────────────────────────────────────────────────────────────
def _parse_hook(hook: str) -> List[Tuple[str, Tuple]]:
    """Parse hook string with [y]...[/y] (yellow) and [r]...[/r] (red) tags.
    Returns list of (word, color) tuples."""
    result = []
    pattern = re.compile(r'\[y\](.*?)\[/y\]|\[r\](.*?)\[/r\]|(\S+)')
    for m in pattern.finditer(hook.strip()):
        if m.group(1):
            result.append((m.group(1), GOLD))
        elif m.group(2):
            result.append((m.group(2), CORAL))
        elif m.group(3):
            result.append((m.group(3), WHITE))
    return result


def _draw_hook_title(overlay: Image.Image, hook_parts: List[Tuple[str, Tuple]],
                     width: int, height: int):
    """Draw the static multi-color bold hook title at the top — premium style."""
    if not hook_parts:
        return

    font_size = max(52, int(width * 0.068))   # bigger than before
    font      = _font_impact(font_size)
    draw      = ImageDraw.Draw(overlay)
    GAP       = int(font_size * 0.26)
    max_w     = int(width * 0.90)
    stroke    = max(3, int(font_size * 0.06))  # thicker stroke = bolder look

    def _measure(parts):
        wws = []
        for word, _ in parts:
            bb = font.getbbox(word.upper())
            wws.append(bb[2] - bb[0])
        return wws, sum(wws) + GAP * (len(wws) - 1)

    word_widths, total_w = _measure(hook_parts)

    # Scale down if too wide
    if total_w > max_w:
        font_size = max(42, int(font_size * 0.80))
        font      = _font(font_size, bold=True)
        GAP       = int(font_size * 0.26)
        stroke    = max(3, int(font_size * 0.06))
        word_widths, total_w = _measure(hook_parts)

    y      = int(height * 0.048)
    line_h = int(font_size * 1.32)

    def _draw_line(parts, widths, ly):
        lw = sum(widths) + GAP * (len(widths) - 1)
        lx = (width - lw) // 2
        for i, (word, color) in enumerate(parts):
            txt = word.upper()
            tw  = widths[i]
            # Heavy multi-layer stroke for bold/premium look
            for s in range(stroke, 0, -1):
                sc_a = int(220 * (s / stroke))
                for dx, dy in [(-s,-s),(0,-s),(s,-s),(-s,0),(s,0),(-s,s),(0,s),(s,s)]:
                    draw.text((lx+dx, ly+dy), txt, font=font, fill=(0,0,0,sc_a))
            # Main colored text
            draw.text((lx, ly), txt, font=font, fill=color+(255,))
            lx += tw + GAP

    # Split into two lines if needed
    if total_w > max_w:
        mid  = len(hook_parts) // 2
        top  = hook_parts[:mid];  top_w  = word_widths[:mid]
        bot  = hook_parts[mid:];  bot_w  = word_widths[mid:]
        _draw_line(top, top_w, y)
        _draw_line(bot, bot_w, y + line_h)
    else:
        _draw_line(hook_parts, word_widths, y)


# ── Easing ────────────────────────────────────────────────────────────────────
def _ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3

def _ease_out_back(t: float, ov: float = 1.5) -> float:
    t = max(0.0, min(1.0, t))
    t -= 1
    return t * t * ((ov + 1) * t + ov) + 1

def _ease_out_bounce(t: float) -> float:
    t = max(0.0, min(1.0, t))
    if t < 1/2.75:     return 7.5625 * t * t
    elif t < 2/2.75:   t -= 1.5/2.75;   return 7.5625*t*t + 0.75
    elif t < 2.5/2.75: t -= 2.25/2.75;  return 7.5625*t*t + 0.9375
    else:               t -= 2.625/2.75; return 7.5625*t*t + 0.984375

def _lerp(a, b, t): return a + (b - a) * max(0.0, min(1.0, t))


# ── Font ──────────────────────────────────────────────────────────────────────
def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    candidates = [
        # Custom downloaded fonts — Anton for impact, Montserrat for clean bold
        "/usr/share/fonts/truetype/custom/Montserrat-ExtraBold.ttf" if bold else "/usr/share/fonts/truetype/custom/Montserrat-Bold.ttf",
        # Fallbacks
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"  if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"   if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/open-sans/OpenSans-Bold.ttf"          if bold else "/usr/share/fonts/truetype/open-sans/OpenSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"           if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except: continue
    return ImageFont.load_default()


def _font_impact(size: int) -> ImageFont.FreeTypeFont:
    """Anton font — used for captions, punchy impact style."""
    candidates = [
        "/usr/share/fonts/truetype/custom/Anton-Regular.ttf",
        "/usr/share/fonts/truetype/custom/Montserrat-ExtraBold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except: continue
    return ImageFont.load_default()


def _font_script(size: int) -> ImageFont.FreeTypeFont:
    """Dancing Script Bold — used for emphasis words, script/italic style."""
    candidates = [
        "/usr/share/fonts/truetype/custom/DancingScript-Bold.ttf",
        "/usr/share/fonts/truetype/custom/Montserrat-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except: continue
    return ImageFont.load_default()


# ── Drawing helpers ────────────────────────────────────────────────────────────
def _rounded_rect(img: Image.Image, bbox: Tuple, radius: int, fill: Tuple, alpha: int = 255):
    x0, y0, x1, y1 = [int(v) for v in bbox]
    color = fill[:3] + (alpha,)
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(ov).rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=color)
    img.alpha_composite(ov)


def _gradient_overlay(img: Image.Image, top_color: Tuple, bot_color: Tuple, alpha: int = 180):
    """Vertical gradient overlay."""
    w, h = img.size
    grad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(grad)
    for y in range(h):
        t = y / h
        r = int(top_color[0]*(1-t) + bot_color[0]*t)
        g = int(top_color[1]*(1-t) + bot_color[1]*t)
        b = int(top_color[2]*(1-t) + bot_color[2]*t)
        a = int(alpha*(1 - abs(t-0.5)*0.8))
        draw.line([(0, y), (w, y)], fill=(r, g, b, a))
    img.alpha_composite(grad)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> List[str]:
    words = text.split()
    lines: List[str] = []
    cur: List[str] = []
    for w in words:
        cur.append(w)
        bb = font.getbbox(" ".join(cur))
        if bb[2] - bb[0] > max_w:
            if len(cur) > 1:
                lines.append(" ".join(cur[:-1]))
                cur = [w]
            else:
                lines.append(w)
                cur = []
    if cur:
        lines.append(" ".join(cur))
    return [l for l in lines if l]


# ── FFmpeg streaming helpers ───────────────────────────────────────────────────
def _start_rgb_pipe(width: int, height: int, fps: int, output_path: str,
                    duration: float, audio_path: Optional[str] = None):
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{width}x{height}", "-pix_fmt", "rgb24",
        "-r", str(fps), "-i", "pipe:0",
    ]
    if audio_path and os.path.exists(audio_path):
        cmd += ["-i", audio_path, "-c:a", "aac", "-shortest"]
    else:
        cmd += ["-f", "lavfi", "-i",
                f"anullsrc=r=44100:cl=stereo:d={duration}",
                "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-crf", "18", "-preset", "slow", output_path]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)


def _write_frame(proc, frame_img: Image.Image, mode: str = "RGB"):
    proc.stdin.write(np.array(frame_img.convert(mode)).tobytes())


# ── Caption renderer ──────────────────────────────────────────────────────────
# Emphasis color palette — cycles through these for highlighted words
EMPH_COLORS = [GOLD, (120, 230, 80), ORANGE, CORAL]


def _stroke_text(draw: ImageDraw.ImageDraw, pos: Tuple, text: str,
                 font: ImageFont.FreeTypeFont, fill: Tuple, stroke: int = 3):
    """Draw text with a solid black outline for readability on any background."""
    x, y = pos
    sc = (0, 0, 0, 200)
    for dx, dy in [(-stroke,-stroke),(0,-stroke),(stroke,-stroke),
                   (-stroke,0),              (stroke,0),
                   (-stroke, stroke),(0, stroke),(stroke, stroke)]:
        draw.text((x+dx, y+dy), text, font=font, fill=sc)
    draw.text((x, y), text, font=font, fill=fill)


def _glow_text(overlay: Image.Image, pos: Tuple, text: str,
               font: ImageFont.FreeTypeFont, color: Tuple,
               radius: int = 8, strength: int = 60):
    """Draw a soft blurred glow behind text for a premium lit look."""
    glow = Image.new("RGBA", overlay.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).text(pos, text, font=font, fill=color + (strength,))
    overlay.alpha_composite(glow.filter(ImageFilter.GaussianBlur(radius)))


def _detect_emphasis(word: Dict, prev_word: Optional[Dict]) -> bool:
    """Mark a word as emphasis if it's held long or repeated."""
    duration = word["end"] - word["start"]
    txt = word["word"].strip().lower()
    prev_txt = prev_word["word"].strip().lower() if prev_word else ""
    return duration >= 0.28 or (txt == prev_txt and txt != "")


def render_captions_overlay(
    words: List[Dict],
    clip_path: str,
    output_path: str,
    width: int = 1920,
    height: int = 1080,
    fps: int = FPS,
    max_words: int = 4,
    hook: str = "",
    caption_position: str = "bottom",   # "top" | "center" | "bottom"
    caption_style: str = "clean",       # "clean" | "mixed" | "box"
):
    """
    Premium 2-line caption style — no boxes, stroke outline, word-by-word reveal.
    Emphasis words get color. Hook title drawn at top if provided.
    """
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", clip_path],
        capture_output=True, text=True,
    )
    try:
        duration = float(probe.stdout.strip())
    except ValueError:
        duration = words[-1]["end"] if words else 10.0

    total_frames = int(duration * fps)

    # ── Fonts ─────────────────────────────────────────────────────────────────
    font_size = max(46, int(width * 0.056))
    font      = _font_impact(font_size)
    # Mixed style uses Dancing Script for emphasis; others use same font
    font_emph = _font_script(int(font_size * 1.18)) if caption_style == "mixed" else font
    space_w    = max(10, int(font_size * 0.24))
    safe_w     = int(width * 0.84)
    stroke_px  = max(2, int(font_size * 0.05))

    # ── Pre-group words into lines (fit within safe_w) ────────────────────────
    clean_words = [w for w in words if w["word"].strip()]
    lines: List[List[Dict]] = []
    cur_line: List[Dict] = []
    cur_w = 0

    for w in clean_words:
        txt = w["word"].strip().upper()
        bb  = font.getbbox(txt)
        ww  = bb[2] - bb[0] + space_w
        if cur_w + ww > safe_w and cur_line:
            lines.append(cur_line)
            cur_line = [w]
            cur_w    = ww
        else:
            cur_line.append(w)
            cur_w += ww
    if cur_line:
        lines.append(cur_line)

    # ── Pre-compute layout (x position, emphasis, color) for each word ────────
    line_layouts: List[List[Dict]] = []
    emph_counter = 0
    for line in lines:
        layout = []
        # Measure total width using correct font per word
        total_w = 0
        for w in line:
            is_e = _detect_emphasis(w, None)
            f    = font_emph if is_e else font
            txt  = w["word"].strip() if is_e else w["word"].strip().upper()
            bb   = f.getbbox(txt)
            total_w += (bb[2] - bb[0]) + space_w
        total_w = max(0, total_w - space_w)
        x    = max(int(width * 0.04), (width - total_w) // 2)
        prev = None
        for w in line:
            emph  = _detect_emphasis(w, prev) if caption_style != "box" else False
            f     = font_emph if emph else font
            # Mixed: script font keeps natural case; others uppercase
            txt   = w["word"].strip() if (emph and caption_style == "mixed") else w["word"].strip().upper()
            bb    = f.getbbox(txt)
            ww    = bb[2] - bb[0]
            wh    = bb[3] - bb[1]
            color = EMPH_COLORS[emph_counter % len(EMPH_COLORS)] if emph else WHITE
            if emph:
                emph_counter += 1
            layout.append({"word": w, "text": txt, "font": f, "x": x,
                            "w": ww, "h": wh, "emph": emph, "color": color})
            x += ww + space_w
            prev = w
        line_layouts.append(layout)

    # ── Vertical positions based on caption_position ─────────────────────────
    line_h = int(font_size * 1.5)
    margin = int(height * 0.10)

    if caption_position == "top":
        line1_y = margin
        line2_y = line1_y + line_h + int(font_size * 0.12)
    elif caption_position == "center":
        mid     = height // 2
        line1_y = mid - line_h - int(font_size * 0.12)
        line2_y = mid
    else:  # bottom (default)
        line2_y = height - margin - line_h
        line1_y = line2_y - line_h - int(font_size * 0.12)

    hook_parts = _parse_hook(hook) if hook.strip() else []

    # Cinematic pre-computation
    cin_blocks = []
    if caption_style == "cinematic":
        LINE_GAP    = int(font_size * 0.55)
        cin_reg     = _font_impact(int(font_size * 1.02))
        cin_emph    = _font_script(int(font_size * 2.30))  # bigger = more dramatic
        safe_line_w = int(width * 0.80)
        emph_c      = 0
        BLOCK_DUR   = 2.5

        def _cin_is_emph(w, prev):
            dur = w["end"] - w["start"]
            txt = w["word"].strip().lower()
            ptx = prev["word"].strip().lower() if prev else ""
            return dur >= 0.22 or txt == ptx

        all_rows = []
        i = 0
        prev = None
        while i < len(clean_words):
            w = clean_words[i]
            if _cin_is_emph(w, prev):
                color = EMPH_COLORS[emph_c % len(EMPH_COLORS)]
                emph_c += 1
                txt = w["word"].strip()
                bb  = cin_emph.getbbox(txt)
                all_rows.append([{"word": w, "text": txt, "font": cin_emph,
                                   "w": bb[2]-bb[0], "h": bb[3]-bb[1],
                                   "emph": True, "color": color}])
                prev = w; i += 1
            else:
                row_items = []
                row_w = 0
                while i < len(clean_words) and len(row_items) < 2:
                    ww = clean_words[i]
                    if _cin_is_emph(ww, prev):
                        break
                    txt2 = ww["word"].strip().upper()
                    bb2  = cin_reg.getbbox(txt2)
                    ww2  = bb2[2] - bb2[0]
                    if row_w + ww2 > safe_line_w and row_items:
                        break
                    row_items.append({"word": ww, "text": txt2, "font": cin_reg,
                                      "w": ww2, "h": bb2[3]-bb2[1],
                                      "emph": False, "color": WHITE})
                    row_w += ww2 + space_w
                    prev = ww; i += 1
                if row_items:
                    all_rows.append(row_items)

        for row in all_rows:
            total_w = sum(it["w"] for it in row) + space_w*(len(row)-1)
            x = (width - total_w) // 2
            max_h = max(it["h"] for it in row)
            for it in row:
                it["x"] = x
                it["y_off"] = (max_h - it["h"]) // 2
                x += it["w"] + space_w

        blk_rows = []
        blk_start_t = None
        for row in all_rows:
            first_t = row[0]["word"]["start"]
            if blk_start_t is None:
                blk_start_t = first_t
            if first_t - blk_start_t > BLOCK_DUR and blk_rows:
                aw = [it["word"] for r in blk_rows for it in r]
                cin_blocks.append({"start": aw[0]["start"], "end": aw[-1]["end"], "rows": blk_rows})
                blk_rows = [row]; blk_start_t = first_t
            else:
                blk_rows.append(row)
        if blk_rows:
            aw = [it["word"] for r in blk_rows for it in r]
            cin_blocks.append({"start": aw[0]["start"], "end": aw[-1]["end"], "rows": blk_rows})

        # Detect face region to place captions in empty space
        face_y_frac = _detect_face_region(clip_path, height)
        if face_y_frac < 0.40:
            # Face at top → captions in lower half
            caption_center_y = int(height * 0.72)
        elif face_y_frac > 0.60:
            # Face at bottom → captions in upper half
            caption_center_y = int(height * 0.28)
        else:
            # Face in center → captions slightly below center
            caption_center_y = int(height * 0.62)

        for blk in cin_blocks:
            row_heights = [max(it["h"] for it in r) for r in blk["rows"]]
            block_h = sum(row_heights) + LINE_GAP*(len(blk["rows"])-1)
            y = caption_center_y - block_h // 2
            # Clamp so block never goes off screen
            y = max(int(height * 0.05), min(y, int(height * 0.90) - block_h))
            blk["row_ys"] = []
            for rh in row_heights:
                blk["row_ys"].append(y)
                y += rh + LINE_GAP

    # ── FFmpeg overlay pipeline ───────────────────────────────────────────────
    cmd = [
        "ffmpeg", "-y",
        "-i", clip_path,
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{width}x{height}", "-pix_fmt", "rgba",
        "-r", str(fps), "-i", "pipe:0",
        "-filter_complex", "[0:v][1:v]overlay=format=auto[v]",
        "-map", "[v]", "-map", "0:a",
        "-sn", "-c:v", "libx264", "-c:a", "aac",
        "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "slow",
        output_path,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

    try:
        for fi in range(total_frames):
            t = fi / fps

            overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw    = ImageDraw.Draw(overlay)

            # ── Hook title at top ─────────────────────────────────────────
            if hook_parts:
                _draw_hook_title(overlay, hook_parts, width, height)

            # ── Cinematic style ───────────────────────────────────────────
            if caption_style == "cinematic":
                curr_blk = None
                for blk in cin_blocks:
                    if blk["start"] <= t <= blk["end"] + 0.4:
                        curr_blk = blk
                        break

                if curr_blk:
                    for ri, row in enumerate(curr_blk["rows"]):
                        row_y = curr_blk["row_ys"][ri]
                        # Only show this row if its first word has started
                        first_word_start = row[0]["word"]["start"]
                        if first_word_start > t:
                            continue  # row not yet reached

                        for item in row:
                            w = item["word"]
                            if w["start"] > t:
                                continue  # word not yet spoken
                            elapsed   = t - w["start"]
                            alpha     = int(255 * min(1.0, elapsed / 0.09))
                            is_active = w["start"] <= t < w["end"]
                            iy        = row_y + item.get("y_off", 0)

                            if is_active and not item["emph"]:
                                color = ORANGE + (alpha,)
                            else:
                                color = item["color"] + (alpha,)

                            _stroke_text(draw, (item["x"], iy), item["text"],
                                         item["font"], color, stroke_px)
                            _glow_text(overlay, (item["x"], iy), item["text"],
                                       item["font"],
                                       ORANGE if (is_active and not item["emph"])
                                       else item["color"],
                                       radius=14 if is_active else 7,
                                       strength=min(95 if is_active else 55, alpha))

                proc.stdin.write(np.array(overlay).tobytes())
                continue  # skip the 2-line logic below

            # ── Find current line index ───────────────────────────────────
            curr_idx = 0
            for i, line in enumerate(lines):
                if line[0]["start"] <= t:
                    curr_idx = i
                else:
                    break

            # ── Draw top line (previous, fully revealed) ──────────────────
            if curr_idx > 0:
                prev_layout = line_layouts[curr_idx - 1]
                for item in prev_layout:
                    _stroke_text(draw, (item["x"], line1_y), item["text"],
                                 item["font"], item["color"] + (220,), stroke_px)
                    _glow_text(overlay, (item["x"], line1_y), item["text"],
                               item["font"], WHITE, radius=6, strength=55)

            # ── Draw bottom line (current, word by word) ──────────────────
            curr_layout = line_layouts[curr_idx]
            for item in curr_layout:
                w = item["word"]
                if w["start"] > t:
                    continue  # not spoken yet

                elapsed = t - w["start"]
                alpha   = int(255 * min(1.0, elapsed / 0.10))

                is_active = w["start"] <= t < w["end"]

                if is_active and item["emph"]:
                    color = item["color"] + (alpha,)
                elif is_active:
                    color = ORANGE + (alpha,)
                else:
                    color = item["color"] + (alpha,)

                if caption_style == "box":
                    # Box style — orange box on active, dark box on others
                    bh  = item["h"] + 22
                    bx0 = max(0, item["x"] - 10)
                    bx1 = min(width, item["x"] + item["w"] + 10)
                    by0 = line2_y - bh // 2
                    by1 = by0 + bh
                    box_color = ORANGE if is_active else DARK_BOX
                    box_alpha = min(235 if is_active else 210, alpha)
                    _rounded_rect(overlay, (bx0, by0, bx1, by1), 12, box_color, box_alpha)
                    draw.text((item["x"]+1, by0 + (bh - item["h"]) // 2 + 1),
                              item["text"], font=item["font"], fill=(0,0,0,min(100,alpha)))
                    draw.text((item["x"],   by0 + (bh - item["h"]) // 2),
                              item["text"], font=item["font"], fill=color)
                else:
                    # Clean / Mixed — stroke + glow, no boxes
                    _stroke_text(draw, (item["x"], line2_y), item["text"],
                                 item["font"], color, stroke_px)
                    if is_active:
                        _glow_text(overlay, (item["x"], line2_y), item["text"],
                                   item["font"], ORANGE if not item["emph"] else item["color"],
                                   radius=10, strength=min(80, alpha))
                    else:
                        _glow_text(overlay, (item["x"], line2_y), item["text"],
                                   item["font"], WHITE, radius=5, strength=min(45, alpha))

            proc.stdin.write(np.array(overlay).tobytes())
    finally:
        proc.stdin.close()
        proc.wait()

    if proc.returncode != 0:
        raise RuntimeError("Caption overlay failed")


# ── Intro renderer ────────────────────────────────────────────────────────────
def render_intro(
    bg_frame_path: str,
    output_path: str,
    channel: str,
    clip_title: str,
    duration: float = 3.0,
    width: int = 1920,
    height: int = 1080,
    fps: int = FPS,
):
    total_frames = int(duration * fps)
    safe_x     = int(width * 0.08)
    max_text_w = width - 2 * safe_x

    bg    = Image.open(bg_frame_path).convert("RGB").resize((width, height), Image.LANCZOS)
    bg_np = np.array(bg.filter(ImageFilter.GaussianBlur(18)), dtype=np.float32)

    # Pick title font — wrap to fit
    for title_fs in [82, 68, 56, 46]:
        font_ti     = _font(title_fs, bold=True)
        title_lines = _wrap_text(clip_title.upper(), font_ti, max_text_w)[:3]
        if all(font_ti.getbbox(ln)[2]-font_ti.getbbox(ln)[0] <= max_text_w for ln in title_lines):
            break

    ti_stroke  = max(3, int(title_fs * 0.055))

    # Channel name — scale down font until it fits on one line, max 2 lines
    for ch_fs in [int(title_fs * 0.46), int(title_fs * 0.38), int(title_fs * 0.32), 28]:
        ch_fs   = max(28, ch_fs)
        font_ch = _font(ch_fs, bold=True)
        ch_bb   = font_ch.getbbox(channel.upper())
        if ch_bb[2] - ch_bb[0] <= max_text_w:
            ch_lines = [channel.upper()]
            break
        # Try wrapping to 2 lines
        ch_lines = _wrap_text(channel.upper(), font_ch, max_text_w)[:2]
        if all(font_ch.getbbox(l)[2]-font_ch.getbbox(l)[0] <= max_text_w for l in ch_lines):
            break

    ch_stroke = max(2, int(ch_fs * 0.06))
    ch_line_h = int(ch_fs * 1.28)

    # Layout — everything centered
    line_h    = int(title_fs * 1.32)
    ch_h      = ch_line_h * len(ch_lines)
    DECO_H    = 3
    GAP_S     = int(title_fs * 0.28)
    GAP_M     = int(title_fs * 0.52)

    title_block_h = len(title_lines) * line_h
    total_h   = DECO_H + GAP_S + ch_h + GAP_S + DECO_H + GAP_M + title_block_h
    block_top = height // 2 - total_h // 2

    deco1_y   = block_top
    ch_y      = deco1_y + DECO_H + GAP_S
    deco2_y   = ch_y + ch_h + GAP_S
    title_y   = deco2_y + DECO_H + GAP_M

    card_pad  = int(title_fs * 0.55)
    card_x0   = safe_x - card_pad
    card_x1   = width - safe_x + card_pad
    card_y0   = block_top - card_pad
    card_y1   = title_y + title_block_h + card_pad
    deco_x0   = safe_x
    deco_w    = width - 2 * safe_x

    proc = _start_rgb_pipe(width, height, fps, output_path, duration)

    try:
        for fi in range(total_frames):
            t = fi / fps

            # Ken Burns zoom in
            zoom   = 1.0 + 0.12 * _ease_out_cubic(min(1, t / 2.0))
            zw, zh = int(width*zoom), int(height*zoom)
            zoomed = Image.fromarray(bg_np.astype(np.uint8)).resize((zw, zh), Image.LANCZOS)
            cx, cy = (zw-width)//2, (zh-height)//2
            frame  = np.array(zoomed.crop((cx, cy, cx+width, cy+height)), dtype=np.float32)

            dark  = 0.72 * _ease_out_cubic(min(1, t / 0.5))
            frame = np.clip(frame * (1 - dark), 0, 255)

            canvas = Image.fromarray(frame.astype(np.uint8)).convert("RGBA")
            draw   = ImageDraw.Draw(canvas)

            # Glass card — slides up
            card_t = _ease_out_cubic(max(0, (t - 0.1) / 0.45))
            if card_t > 0:
                slide = int((1 - card_t) * 55)
                _rounded_rect(canvas,
                    (card_x0, card_y0-slide, card_x1, card_y1-slide),
                    26, (6, 6, 14), int(195 * card_t))
                # Orange glow halo
                glow = Image.new("RGBA", (width, height), (0,0,0,0))
                ImageDraw.Draw(glow).rounded_rectangle(
                    [card_x0-18, card_y0-slide-18, card_x1+18, card_y1-slide+18],
                    radius=32, fill=ORANGE+(int(28*card_t),)
                )
                canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(22)))

            # Two orange decorative lines (draw left→right simultaneously)
            deco_t = _ease_out_cubic(max(0, (t - 0.22) / 0.38))
            if deco_t > 0:
                ll = int(deco_w * deco_t)
                draw.line([(deco_x0, deco1_y), (deco_x0+ll, deco1_y)], fill=ORANGE+(225,), width=3)
                draw.line([(deco_x0, deco2_y), (deco_x0+ll, deco2_y)], fill=ORANGE+(225,), width=3)

            # Channel name — centered, slides from left, gold color (multi-line safe)
            ch_t = _ease_out_cubic(max(0, (t - 0.32) / 0.4))
            ch_a = int(255 * ch_t)
            if ch_a > 0:
                for li, ln in enumerate(ch_lines):
                    ch_bb = font_ch.getbbox(ln)
                    ch_w  = ch_bb[2] - ch_bb[0]
                    ch_x_final = (width - ch_w) // 2
                    ch_x = ch_x_final + int((1 - ch_t) * (-width * 0.38))
                    ch_x = max(safe_x, min(ch_x, width - safe_x - ch_w))
                    _stroke_text(draw, (ch_x, ch_y + li * ch_line_h), ln, font_ch,
                                 GOLD+(ch_a,), ch_stroke)

            # Title lines — centered, slam in from bottom with stagger
            for li, ln in enumerate(title_lines):
                stagger = li * 0.09
                ti_t = _ease_out_back(max(0, (t - 0.52 - stagger) / 0.44), ov=1.3)
                ti_a = int(255 * _ease_out_cubic(max(0, (t - 0.52 - stagger) / 0.28)))
                if ti_a <= 0:
                    continue
                bb = font_ti.getbbox(ln)
                tw = bb[2] - bb[0]
                tx = max(safe_x, (width - tw) // 2)
                ty = title_y + li * line_h + int((1 - ti_t) * 220)
                _stroke_text(draw, (tx, ty), ln, font_ti, WHITE+(ti_a,), ti_stroke)

            # White flash at end
            flash_t = max(0, (t - (duration - 0.2)) / 0.2)
            if flash_t > 0:
                canvas.alpha_composite(
                    Image.new("RGBA", (width, height), (255,255,255,int(255*flash_t))))

            _write_frame(proc, canvas, "RGB")
    finally:
        proc.stdin.close()
        proc.wait()


# ── Outro renderer ────────────────────────────────────────────────────────────
def render_outro(
    bg_frame_path: str,
    output_path: str,
    handle: str,
    duration: float = 3.0,
    width: int = 1920,
    height: int = 1080,
    fps: int = FPS,
):
    total_frames = int(duration * fps)
    safe_x     = int(width * 0.08)
    max_text_w = width - 2 * safe_x

    bg    = Image.open(bg_frame_path).convert("RGB").resize((width, height), Image.LANCZOS)
    bg_np = np.array(bg.filter(ImageFilter.GaussianBlur(20)), dtype=np.float32)

    cta = "FOLLOW FOR MORE"
    for cta_fs in [82, 68, 56]:
        font_cta = _font(cta_fs, bold=True)
        bb = font_cta.getbbox(cta)
        if bb[2] - bb[0] <= max_text_w:
            break

    for hdl_fs in [58, 48, 38]:
        font_hdl = _font(hdl_fs, bold=True)
        bb = font_hdl.getbbox(handle)
        if bb[2] - bb[0] <= max_text_w:
            break

    cta_stroke = max(3, int(cta_fs * 0.055))
    hdl_stroke = max(2, int(hdl_fs * 0.06))

    cta_bb = font_cta.getbbox(cta)
    cta_w  = cta_bb[2]-cta_bb[0]; cta_h = cta_bb[3]-cta_bb[1]
    hdl_bb = font_hdl.getbbox(handle)
    hdl_w  = hdl_bb[2]-hdl_bb[0]; hdl_h = hdl_bb[3]-hdl_bb[1]

    UL_H    = 5
    ACC_GAP = int(cta_fs * 0.38)   # gap: top accent line → CTA
    UL_GAP  = int(cta_fs * 0.18)   # gap: CTA → underline
    HDL_GAP = int(cta_fs * 0.48)   # gap: underline → handle

    total_h   = UL_H + ACC_GAP + cta_h + UL_GAP + UL_H + HDL_GAP + hdl_h
    block_top = height // 2 - total_h // 2

    acc_y  = block_top
    cta_y  = acc_y  + UL_H + ACC_GAP
    ul_y   = cta_y  + cta_h + UL_GAP
    hdl_y  = ul_y   + UL_H + HDL_GAP

    # All centered horizontally
    cta_x  = (width - cta_w) // 2
    hdl_x  = (width - hdl_w) // 2
    ul_x0  = cta_x
    ul_x1  = cta_x + cta_w

    card_pad = int(cta_fs * 0.55)
    card_x0  = safe_x - card_pad
    card_x1  = width - safe_x + card_pad
    card_y0  = block_top - card_pad
    card_y1  = hdl_y + hdl_h + card_pad

    proc = _start_rgb_pipe(width, height, fps, output_path, duration)

    try:
        for fi in range(total_frames):
            t = fi / fps

            # Zoom out
            zoom  = 1.15 - 0.12 * _ease_out_cubic(min(1, t / duration))
            zw, zh = int(width*zoom), int(height*zoom)
            zoomed = Image.fromarray(bg_np.astype(np.uint8)).resize((zw, zh), Image.LANCZOS)
            if zw >= width and zh >= height:
                ox, oy = (zw-width)//2, (zh-height)//2
                frame  = np.array(zoomed.crop((ox,oy,ox+width,oy+height)), dtype=np.float32)
            else:
                frame = bg_np.copy()

            dark  = 0.72 * _ease_out_cubic(min(1, t / 0.5))
            frame = np.clip(frame * (1 - dark), 0, 255)
            canvas = Image.fromarray(frame.astype(np.uint8)).convert("RGBA")
            draw   = ImageDraw.Draw(canvas)

            # Glass card
            card_t = _ease_out_cubic(max(0, (t - 0.1) / 0.4))
            if card_t > 0:
                _rounded_rect(canvas, (card_x0, card_y0, card_x1, card_y1),
                              26, (6, 6, 14), int(195 * card_t))
                glow = Image.new("RGBA", (width, height), (0,0,0,0))
                ImageDraw.Draw(glow).rounded_rectangle(
                    [card_x0-18, card_y0-18, card_x1+18, card_y1+18],
                    radius=32, fill=ORANGE+(int(22*card_t),)
                )
                canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(20)))

            # Top accent line — draws left→right, centered under CTA
            acc_t = _ease_out_cubic(max(0, (t - 0.2) / 0.38))
            if acc_t > 0:
                ll = int((ul_x1 - ul_x0) * acc_t)
                draw.line([(ul_x0, acc_y), (ul_x0+ll, acc_y)], fill=ORANGE+(230,), width=UL_H)

            # CTA — centered, slides from right
            cta_t = _ease_out_cubic(max(0, (t - 0.32) / 0.48))
            cta_a = int(255 * cta_t)
            if cta_a > 0:
                slide = int((1 - cta_t) * min(480, width * 0.32))
                sx = min(cta_x + slide, width - safe_x - cta_w)
                sx = max(safe_x, sx)
                _stroke_text(draw, (sx, cta_y), cta, font_cta, WHITE+(cta_a,), cta_stroke)

                # Underline draws at final centered position
                ul_t = _ease_out_cubic(max(0, (t - 0.72) / 0.42))
                if ul_t > 0:
                    ll = int((ul_x1 - ul_x0) * ul_t)
                    draw.line([(ul_x0, ul_y), (ul_x0+ll, ul_y)], fill=ORANGE+(230,), width=UL_H)

            # Handle — gold glow + bounces in from below
            hdl_t = _ease_out_back(max(0, (t - 0.88) / 0.48), ov=1.35)
            hdl_a = int(255 * _ease_out_cubic(max(0, (t - 0.88) / 0.3)))
            if hdl_a > 0:
                hy = hdl_y + int((1 - hdl_t) * 65)
                # Gold glow layer
                glow2 = Image.new("RGBA", (width, height), (0,0,0,0))
                ImageDraw.Draw(glow2).text((hdl_x, hy), handle, font=font_hdl,
                                           fill=GOLD+(hdl_a,))
                canvas.alpha_composite(glow2.filter(ImageFilter.GaussianBlur(14)))
                _stroke_text(draw, (hdl_x, hy), handle, font_hdl, GOLD+(hdl_a,), hdl_stroke)

            # Vignette
            vign_t = _ease_out_cubic(min(1, t / 0.8))
            if vign_t > 0.05:
                vign = Image.new("RGBA", (width, height), (0,0,0,0))
                for r_frac, a in [(0.48, 90), (0.60, 45), (0.72, 20)]:
                    rw = int(width*r_frac); rh = int(height*r_frac)
                    ImageDraw.Draw(vign).ellipse(
                        [(width//2-rw, height//2-rh), (width//2+rw, height//2+rh)],
                        outline=(0,0,0,int(a*vign_t)), width=int(width*0.08)
                    )
                canvas.alpha_composite(vign)

            _write_frame(proc, canvas, "RGB")
    finally:
        proc.stdin.close()
        proc.wait()


# ── Shorts captions (same logic, different resolution) ────────────────────────
def render_captions_overlay_shorts(
    words: List[Dict],
    clip_path: str,
    output_path: str,
    width: int = 1080,
    height: int = 1920,
    fps: int = FPS,
    max_words: int = 3,
    hook: str = "",
    caption_position: str = "bottom",
    caption_style: str = "clean",
):
    render_captions_overlay(
        words=words, clip_path=clip_path, output_path=output_path,
        width=width, height=height, fps=fps, max_words=max_words,
        hook=hook, caption_position=caption_position, caption_style=caption_style,
    )
