import re
from dataclasses import dataclass
from typing import List, Dict


@dataclass
class SRTEntry:
    index: int
    start: float
    end: float
    text: str


def _parse_time(t: str) -> float:
    h, m, rest = t.strip().split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def _format_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds % 1) * 100))
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def _ass_header(play_res_x: int, play_res_y: int, margin_v: int, fontsize: int = 60,
                primary: str = "&H00FFFFFF", secondary: str = "&H0000FFFF") -> str:
    return (
        f"[Script Info]\n"
        f"ScriptType: v4.00+\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        f"ScaledBorderAndShadow: yes\n\n"
        f"[V4+ Styles]\n"
        f"Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        f"Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        f"Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,Arial,{fontsize},{primary},{secondary},&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,3,1,2,10,10,{margin_v},1\n\n"
        f"[Events]\n"
        f"Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def parse_srt(content: str) -> List[SRTEntry]:
    entries = []
    blocks = re.split(r"\n\s*\n", content.strip())
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        try:
            idx = int(lines[0].strip())
            times = lines[1].split(" --> ")
            start = _parse_time(times[0])
            end = _parse_time(times[1])
            text = "\n".join(lines[2:])
            entries.append(SRTEntry(idx, start, end, text))
        except (ValueError, IndexError):
            continue
    return entries


def trim_srt(entries: List[SRTEntry], clip_start: float, clip_end: float) -> List[SRTEntry]:
    result = []
    for i, e in enumerate(entries, start=1):
        if e.end <= clip_start or e.start >= clip_end:
            continue
        new_start = max(0.0, e.start - clip_start)
        new_end = min(clip_end - clip_start, e.end - clip_start)
        result.append(SRTEntry(i, new_start, new_end, e.text))
    return result


def trim_words(words: List[Dict], clip_start: float, clip_end: float) -> List[Dict]:
    """Filter word timestamps to a clip window and re-zero the timestamps."""
    result = []
    for w in words:
        if w["end"] <= clip_start or w["start"] >= clip_end:
            continue
        result.append({
            "word": w["word"],
            "start": max(0.0, w["start"] - clip_start),
            "end":   min(clip_end - clip_start, w["end"] - clip_start),
        })
    return result


def entries_to_ass(entries: List[SRTEntry], play_res_x: int = 1920, play_res_y: int = 1080, margin_v: int = 80) -> str:
    """Plain subtitles with fade — fallback when no word timestamps are available."""
    header = _ass_header(play_res_x, play_res_y, margin_v, fontsize=56)
    lines = []
    for e in entries:
        text = e.text.replace("\n", "\\N")
        lines.append(
            f"Dialogue: 0,{_format_ass_time(e.start)},{_format_ass_time(e.end)},"
            f"Default,,0,0,0,,{{\\fad(150,150)}}{text}"
        )
    return header + "\n".join(lines)


def words_to_animated_ass(
    words: List[Dict],
    play_res_x: int = 1920,
    play_res_y: int = 1080,
    margin_v: int = 100,
    max_words_per_line: int = 5,
    max_line_duration: float = 3.0,
) -> str:
    """
    CapCut-style animated captions using ASS karaoke tags.
    Words are grouped into short lines; each word highlights in yellow
    as it is spoken while the rest of the line stays white.
    """
    if not words:
        return entries_to_ass([], play_res_x, play_res_y, margin_v)

    # Group words into lines
    groups: List[tuple] = []  # (line_start, line_end, [words])
    current: List[Dict] = []
    line_start = None

    for w in words:
        text = w["word"].strip()
        if not text:
            continue
        if not current:
            line_start = w["start"]
        current.append(w)
        if len(current) >= max_words_per_line or (w["end"] - line_start) >= max_line_duration:
            groups.append((line_start, current[-1]["end"], current))
            current = []
            line_start = None

    if current:
        groups.append((line_start, current[-1]["end"], current))

    # ASS header — primary white, secondary yellow (karaoke highlight colour)
    header = _ass_header(play_res_x, play_res_y, margin_v, fontsize=64,
                         primary="&H00FFFFFF", secondary="&H0000FFFF")

    dialogue: List[str] = []
    for line_start, line_end, group in groups:
        parts = []
        for w in group:
            duration_cs = max(1, int(round((w["end"] - w["start"]) * 100)))
            # \kf = smooth karaoke fill (highlights progressively)
            parts.append(f"{{\\kf{duration_cs}}}{w['word'].strip()}")
        text = " ".join(parts)
        # Fade the whole line in/out slightly
        fade = "{\\fad(80,80)}"
        dialogue.append(
            f"Dialogue: 0,{_format_ass_time(line_start)},{_format_ass_time(line_end)},"
            f"Default,,0,0,0,,{fade}{text}"
        )

    return header + "\n".join(dialogue)
