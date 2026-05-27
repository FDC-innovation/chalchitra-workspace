"""
Chalchitra Visual Renderer
Pillow + numpy based frame-by-frame animation engine.
Streams frames directly to FFmpeg — no full-video RAM usage.
"""
import os
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from typing import List, Dict, Tuple, Optional, Iterator

FPS = 15

ORANGE   = (255, 140,   0)
WHITE    = (255, 255, 255)
BLACK    = (  0,   0,   0)
GOLD     = (255, 200,   0)
DARK_BOX = ( 15,  15,  15)
CORAL    = (255,  80,  60)
CYAN     = ( 80, 220, 255)


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
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"    if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"     if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/open-sans/OpenSans-Bold.ttf"            if bold else "/usr/share/fonts/truetype/open-sans/OpenSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"             if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
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
            "-preset", "fast", output_path]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)


def _write_frame(proc, frame_img: Image.Image, mode: str = "RGB"):
    proc.stdin.write(np.array(frame_img.convert(mode)).tobytes())


# ── Caption renderer ──────────────────────────────────────────────────────────
def render_captions_overlay(
    words: List[Dict],
    clip_path: str,
    output_path: str,
    width: int = 1920,
    height: int = 1080,
    fps: int = FPS,
    max_words: int = 4,
):
    """
    CapCut-style word-by-word animated captions overlaid on a video.
    Auto-scales font sizes to guarantee all words stay within frame bounds.
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

    groups = []
    current: List[Dict] = []
    line_start = None
    for w in words:
        txt = w["word"].strip()
        if not txt:
            continue
        if not current:
            line_start = w["start"]
        current.append(w)
        if len(current) >= max_words or (w["end"] - line_start) >= 2.5:
            groups.append((line_start, current[-1]["end"], list(current)))
            current = []
            line_start = None
    if current:
        groups.append((line_start, current[-1]["end"], current))

    PAD_X, PAD_Y  = 20, 12
    GAP           = 8
    # Caption strip sits at 78% height, never touching the bottom edge
    cap_center_y  = int(height * 0.78)
    # Keep a safe margin from the sides
    safe_margin   = int(width * 0.04)
    max_cap_w     = width - 2 * safe_margin

    # Pick font sizes that guarantee the widest possible group fits within frame
    def _pick_font_sizes(groups_list):
        for fs_active, fs_inactive in [(68, 54), (58, 46), (48, 38), (38, 30)]:
            fa = _font(fs_active, bold=True)
            fi = _font(fs_inactive, bold=True)
            fits = True
            for _, _, gw in groups_list:
                bws = []
                for i, w in enumerate(gw):
                    f = fa if i == 0 else fi
                    bb = f.getbbox(w["word"].strip().upper())
                    bws.append(bb[2]-bb[0] + 2*PAD_X)
                total_w = sum(bws) + GAP*(len(bws)-1)
                if total_w > max_cap_w:
                    fits = False
                    break
            if fits:
                return fs_active, fs_inactive, fa, fi
        # Fallback: smallest sizes
        fa = _font(38, bold=True)
        fi = _font(30, bold=True)
        return 38, 30, fa, fi

    fs_active, fs_inactive, font_active, font_inactive = _pick_font_sizes(groups)

    cmd = [
        "ffmpeg", "-y",
        "-i", clip_path,
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{width}x{height}", "-pix_fmt", "rgba",
        "-r", str(fps), "-i", "pipe:0",
        "-filter_complex", "[0:v][1:v]overlay=format=auto[v]",
        "-map", "[v]", "-map", "0:a",
        "-sn",
        "-c:v", "libx264", "-c:a", "aac",
        "-pix_fmt", "yuv420p", "-preset", "fast",
        output_path,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

    try:
        for fi in range(total_frames):
            t = fi / fps

            overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw    = ImageDraw.Draw(overlay)

            active_group = None
            for gs, ge, gw in groups:
                if gs <= t < ge:
                    active_group = (gs, ge, gw)
                    break

            if active_group:
                gs, ge, gw = active_group
                active_idx = 0
                for i, w in enumerate(gw):
                    if w["start"] <= t:
                        active_idx = i

                items = []
                for i, w in enumerate(gw):
                    is_active = (i == active_idx)
                    font = font_active if is_active else font_inactive
                    text = w["word"].strip().upper()
                    bbox = font.getbbox(text)
                    items.append({
                        "text": text, "font": font,
                        "tw": bbox[2]-bbox[0], "th": bbox[3]-bbox[1],
                        "active": is_active, "word": w,
                    })

                box_widths = [it["tw"] + 2*PAD_X for it in items]
                total_w    = sum(box_widths) + GAP*(len(items)-1)
                # Clamp starting x so group always sits within safe margins
                x = max(safe_margin, (width - total_w) // 2)

                for i, it in enumerate(items):
                    bw = box_widths[i]
                    bh = it["th"] + 2*PAD_Y

                    if it["active"]:
                        elapsed  = t - it["word"]["start"]
                        anim_dur = 0.12
                        scale    = _lerp(0.5, 1.08, _ease_out_bounce(min(1, elapsed/anim_dur))) if elapsed < anim_dur else 1.0

                        sbw = int(bw*scale); sbh = int(bh*scale)
                        bx0 = x + (bw-sbw)//2; by0 = cap_center_y - sbh//2
                        bx1 = bx0+sbw;         by1 = by0+sbh
                        # Clamp box within frame
                        bx0 = max(0, min(bx0, width-sbw))
                        bx1 = min(width, bx1)

                        _rounded_rect(overlay, (bx0,by0,bx1,by1), 14, ORANGE, 235)

                        tx = bx0 + (sbw - int(it["tw"]*scale))//2
                        ty = by0 + (sbh - int(it["th"]*scale))//2
                        # Single thin shadow — 1px so it doesn't read as "double text"
                        draw.text((tx+1, ty+1), it["text"], font=it["font"], fill=(0,0,0,100))
                        draw.text((tx, ty),     it["text"], font=it["font"], fill=WHITE+(255,))
                    else:
                        by0 = cap_center_y - bh//2; by1 = by0+bh
                        rx0 = max(0, x); rx1 = min(width, x+bw)
                        _rounded_rect(overlay, (rx0,by0,rx1,by1), 12, DARK_BOX, 210)
                        # No shadow on inactive words — just white text on dark box
                        draw.text((rx0+PAD_X, by0+PAD_Y), it["text"], font=it["font"], fill=(230,230,230,230))

                    x += bw + GAP

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
    """
    Animated intro: Ken Burns zoom + gradient card + channel name + bouncy title.
    Text is measured, wrapped, and clamped — nothing escapes the frame.
    """
    total_frames = int(duration * fps)
    safe_x = int(width * 0.07)     # left/right safe margin
    max_text_w = width - 2 * safe_x

    bg    = Image.open(bg_frame_path).convert("RGB").resize((width, height), Image.LANCZOS)
    bg_np = np.array(bg.filter(ImageFilter.GaussianBlur(16)), dtype=np.float32)

    # Pick title font size based on length, then wrap
    for title_fs in [80, 66, 54, 44]:
        font_ti = _font(title_fs, bold=True)
        title_lines = _wrap_text(clip_title.upper(), font_ti, max_text_w)[:3]
        # Re-check all lines fit
        if all(font_ti.getbbox(ln)[2] - font_ti.getbbox(ln)[0] <= max_text_w for ln in title_lines):
            break

    ch_fs   = max(36, int(title_fs * 0.52))
    font_ch = _font(ch_fs, bold=True)

    line_h  = int(title_fs * 1.28)
    ch_h    = int(ch_fs * 1.4)
    block_h = ch_h + 12 + len(title_lines) * line_h
    # Centre the whole text block vertically with slight downward bias
    block_top = height // 2 - block_h // 2 + int(height * 0.03)
    title_top = block_top + ch_h + 12

    proc = _start_rgb_pipe(width, height, fps, output_path, duration)

    try:
        for fi in range(total_frames):
            t = fi / fps

            # Ken Burns zoom in
            zoom   = 1.0 + 0.14 * _ease_out_cubic(min(1, t / 1.8))
            zw, zh = int(width*zoom), int(height*zoom)
            zoomed = Image.fromarray(bg_np.astype(np.uint8)).resize((zw, zh), Image.LANCZOS)
            cx, cy = (zw-width)//2, (zh-height)//2
            frame  = np.array(zoomed.crop((cx, cy, cx+width, cy+height)), dtype=np.float32)

            # Darken background
            dark   = 0.62 * _ease_out_cubic(min(1, t / 0.45))
            frame  = np.clip(frame * (1 - dark), 0, 255)

            canvas = Image.fromarray(frame.astype(np.uint8)).convert("RGBA")
            draw   = ImageDraw.Draw(canvas)

            # Gradient card behind the text block (slides up from below)
            card_t = _ease_out_cubic(max(0, (t - 0.15) / 0.5))
            if card_t > 0:
                pad     = 28
                card_x0 = safe_x - pad
                card_x1 = width - safe_x + pad
                card_y0 = block_top - pad - int((1-card_t) * 60)
                card_y1 = title_top + len(title_lines)*line_h + pad
                _rounded_rect(canvas, (card_x0, card_y0, card_x1, card_y1),
                               20, (10, 10, 20), int(175 * card_t))

            # Left orange accent bar
            bar_t = _ease_out_cubic(max(0, (t - 0.2) / 0.4))
            if bar_t > 0:
                bh_full = block_h + 56
                bh = int(bh_full * bar_t)
                by  = height // 2 - bh_full // 2
                _rounded_rect(canvas, (safe_x - 22, by, safe_x - 10, by + bh),
                               4, ORANGE, int(240 * bar_t))

            # Channel name — slides in from left
            ch_t = _ease_out_cubic(max(0, (t - 0.3) / 0.45))
            if ch_t > 0:
                ch_bb  = font_ch.getbbox(channel.upper())
                ch_w   = ch_bb[2] - ch_bb[0]
                ch_x_f = (width - ch_w) // 2        # final: centred
                ch_x   = ch_x_f + int((1 - ch_t) * (-width * 0.4))
                ch_x   = max(safe_x, min(ch_x, width - safe_x - ch_w))
                ch_y   = block_top
                ch_a   = int(255 * ch_t)
                # Orange dot before channel name
                dot_r = int(ch_fs * 0.18)
                draw.ellipse(
                    [ch_x - dot_r*3, ch_y + ch_fs//2 - dot_r,
                     ch_x - dot_r,   ch_y + ch_fs//2 + dot_r],
                    fill=ORANGE + (ch_a,)
                )
                draw.text((ch_x+2, ch_y+2), channel.upper(), font=font_ch, fill=(0,0,0,ch_a//2))
                draw.text((ch_x,   ch_y),   channel.upper(), font=font_ch, fill=WHITE+(ch_a,))

            # Title — each line slams in with stagger
            ti_a_base = int(255 * _ease_out_cubic(max(0, (t - 0.5) / 0.35)))
            for li, ln in enumerate(title_lines):
                stagger = li * 0.08
                ti_t = _ease_out_back(max(0, (t - 0.52 - stagger) / 0.48), ov=1.35)
                ti_a = int(255 * _ease_out_cubic(max(0, (t - 0.52 - stagger) / 0.3)))
                if ti_a <= 0:
                    continue

                bb  = font_ti.getbbox(ln)
                tw  = bb[2] - bb[0]
                tx  = (width - tw) // 2                    # horizontally centred
                tx  = max(safe_x, min(tx, width - safe_x - tw))  # clamp to safe zone
                off = int((1 - ti_t) * 260)
                ty  = title_top + li * line_h + off

                # Drop shadow
                draw.text((tx+4, ty+4), ln, font=font_ti, fill=(0,0,0,int(ti_a*0.65)))
                draw.text((tx,   ty),   ln, font=font_ti, fill=WHITE+(ti_a,))

            # Thin accent line under channel name (draws left→right)
            line_t = _ease_out_cubic(max(0, (t - 0.6) / 0.4))
            if line_t > 0:
                ly    = block_top + ch_h + 4
                lx0   = safe_x
                lx1   = lx0 + int((width - 2*safe_x) * line_t)
                draw.line([(lx0, ly), (lx1, ly)], fill=ORANGE+(210,), width=3)

            # White flash at end
            flash_t = max(0, (t - (duration - 0.18)) / 0.18)
            if flash_t > 0:
                canvas.alpha_composite(Image.new("RGBA", (width,height), (255,255,255,int(255*flash_t))))

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
    """
    Animated outro: zoom out + CTA slides in + underline draws + handle glows.
    All text measured, clamped, and centred — nothing overflows.
    """
    total_frames = int(duration * fps)
    safe_x    = int(width * 0.07)
    max_text_w = width - 2 * safe_x

    bg    = Image.open(bg_frame_path).convert("RGB").resize((width, height), Image.LANCZOS)
    bg_np = np.array(bg.filter(ImageFilter.GaussianBlur(18)), dtype=np.float32)

    cta = "Follow for more"
    for cta_fs in [78, 66, 54]:
        font_cta = _font(cta_fs, bold=True)
        cta_bb   = font_cta.getbbox(cta)
        if cta_bb[2] - cta_bb[0] <= max_text_w:
            break

    for hdl_fs in [54, 44, 36]:
        font_hdl = _font(hdl_fs, bold=True)
        hdl_bb   = font_hdl.getbbox(handle)
        if hdl_bb[2] - hdl_bb[0] <= max_text_w:
            break

    cta_bb  = font_cta.getbbox(cta)
    cta_w   = cta_bb[2] - cta_bb[0];  cta_h = cta_bb[3] - cta_bb[1]
    hdl_bb  = font_hdl.getbbox(handle)
    hdl_w   = hdl_bb[2] - hdl_bb[0];  hdl_h = hdl_bb[3] - hdl_bb[1]

    LINE_GAP  = int(cta_fs * 0.25)
    UNDERLINE = 6
    HDL_GAP   = int(cta_fs * 0.50)

    block_h   = cta_h + LINE_GAP + UNDERLINE + HDL_GAP + hdl_h
    block_top = height // 2 - block_h // 2

    cta_y  = block_top
    line_y = cta_y + cta_h + LINE_GAP
    hdl_y  = line_y + UNDERLINE + HDL_GAP

    # Horizontal centres
    cta_x = max(safe_x, (width - cta_w) // 2)
    hdl_x = max(safe_x, (width - hdl_w) // 2)

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

            dark  = 0.65 * _ease_out_cubic(min(1, t / 0.5))
            frame = np.clip(frame * (1 - dark), 0, 255)
            canvas = Image.fromarray(frame.astype(np.uint8)).convert("RGBA")
            draw   = ImageDraw.Draw(canvas)

            # Dark card behind text block
            card_t = _ease_out_cubic(max(0, (t - 0.1) / 0.45))
            if card_t > 0:
                pad     = 30
                card_x0 = safe_x - pad
                card_x1 = width - safe_x + pad
                card_y0 = block_top - pad
                card_y1 = block_top + block_h + pad
                _rounded_rect(canvas, (card_x0, card_y0, card_x1, card_y1),
                               22, (10, 10, 20), int(170 * card_t))

            # Orange accent bar — left of block
            bar_t = _ease_out_cubic(max(0, (t - 0.2) / 0.4))
            if bar_t > 0:
                bh_full = block_h + 60
                bh  = int(bh_full * bar_t)
                bx  = safe_x - 22
                bby = height // 2 - bh_full // 2
                _rounded_rect(canvas, (bx, bby, bx+12, bby+bh), 4, ORANGE, int(240*bar_t))

            # CTA slides in from right → settles centred
            cta_t = _ease_out_cubic(max(0, (t - 0.3) / 0.5))
            cta_a = int(255 * cta_t)
            if cta_a > 0:
                slide_off = int((1 - cta_t) * min(600, width * 0.4))
                sx = min(cta_x + slide_off, width - safe_x - cta_w)  # clamp right edge
                sx = max(safe_x, sx)
                draw.text((sx+3, cta_y+3), cta, font=font_cta, fill=(0,0,0,int(cta_a*0.65)))
                draw.text((sx,   cta_y),   cta, font=font_cta, fill=WHITE+(cta_a,))

                # Underline draws under settled CTA position
                line_t = _ease_out_cubic(max(0, (t - 0.7) / 0.5))
                if line_t > 0:
                    ll  = int(cta_w * line_t)
                    lx0 = cta_x
                    lx1 = min(lx0 + ll, width - safe_x)
                    draw.line([(lx0, line_y), (lx1, line_y)], fill=ORANGE+(230,), width=UNDERLINE)

            # Handle glows gold, slides in from below
            hdl_t = _ease_out_back(max(0, (t - 0.9) / 0.5), ov=1.3)
            hdl_a = int(255 * _ease_out_cubic(max(0, (t - 0.9) / 0.35)))
            if hdl_a > 0:
                hy  = hdl_y + int((1 - hdl_t) * 70)
                hx  = hdl_x

                # Gold glow
                glow = Image.new("RGBA", (width, height), (0,0,0,0))
                ImageDraw.Draw(glow).text((hx, hy), handle, font=font_hdl, fill=GOLD+(hdl_a,))
                canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(10)))

                draw.text((hx+2, hy+2), handle, font=font_hdl, fill=(80,50,0,int(hdl_a*0.55)))
                draw.text((hx,   hy),   handle, font=font_hdl, fill=GOLD+(hdl_a,))

            # Subtle vignette ring — draws after everything
            vign_t = _ease_out_cubic(min(1, t / 0.8))
            if vign_t > 0.02:
                vign = Image.new("RGBA", (width, height), (0,0,0,0))
                for r_frac, a in [(0.52, 80), (0.62, 40), (0.74, 18)]:
                    rw = int(width * r_frac);  rh = int(height * r_frac)
                    vd = ImageDraw.Draw(vign)
                    vd.ellipse(
                        [(width//2-rw, height//2-rh), (width//2+rw, height//2+rh)],
                        outline=(0,0,0,int(a*vign_t)), width=int(width*0.07)
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
):
    render_captions_overlay(
        words=words, clip_path=clip_path, output_path=output_path,
        width=width, height=height, fps=fps, max_words=max_words,
    )
