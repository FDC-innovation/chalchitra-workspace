import os
import subprocess
from typing import List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

SHARED_DIR = "/app/shared/volumes"

app = FastAPI()


class Segment(BaseModel):
    start_ms: int
    end_ms: int
    type: str


class EditRequest(BaseModel):
    episode_id: str
    file_path: str
    segments: List[Segment]
    padding_ms: int = 150


class EDLEntry(BaseModel):
    start_ms: int
    end_ms: int
    keep: bool
    reason: str


class EditResponse(BaseModel):
    episode_id: str
    edl: List[EDLEntry]
    kept_duration_seconds: float
    removed_duration_seconds: float
    output_file: str


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/edit", response_model=EditResponse)
def edit(req: EditRequest):
    total_ms = max((s.end_ms for s in req.segments), default=0)

    padded = [
        {
            "start_ms": max(0, s.start_ms - req.padding_ms),
            "end_ms": min(total_ms, s.end_ms + req.padding_ms),
        }
        for s in req.segments
        if s.type == "speech"
    ]

    merged = _merge(padded)
    edl = _build_edl(merged, total_ms)

    concat_path = os.path.join(SHARED_DIR, f"{req.episode_id}_concat.txt")
    output_path = os.path.join(SHARED_DIR, f"{req.episode_id}_edited.mp4")

    _write_concat(concat_path, req.file_path, merged)
    _run_ffmpeg(concat_path, output_path, req.file_path)

    kept_ms = sum(s["end_ms"] - s["start_ms"] for s in merged)

    return EditResponse(
        episode_id=req.episode_id,
        edl=edl,
        kept_duration_seconds=round(kept_ms / 1000, 3),
        removed_duration_seconds=round(max(0, total_ms - kept_ms) / 1000, 3),
        output_file=output_path,
    )


def _merge(segments: list) -> list:
    if not segments:
        return []
    segs = sorted(segments, key=lambda s: s["start_ms"])
    merged = [dict(segs[0])]
    for seg in segs[1:]:
        if seg["start_ms"] <= merged[-1]["end_ms"]:
            merged[-1]["end_ms"] = max(merged[-1]["end_ms"], seg["end_ms"])
        else:
            merged.append(dict(seg))
    return merged


def _build_edl(kept: list, total_ms: int) -> List[EDLEntry]:
    edl = []
    cursor = 0
    for seg in kept:
        if seg["start_ms"] > cursor:
            edl.append(EDLEntry(start_ms=cursor, end_ms=seg["start_ms"], keep=False, reason="silence"))
        edl.append(EDLEntry(start_ms=seg["start_ms"], end_ms=seg["end_ms"], keep=True, reason="speech"))
        cursor = seg["end_ms"]
    if cursor < total_ms:
        edl.append(EDLEntry(start_ms=cursor, end_ms=total_ms, keep=False, reason="silence"))
    return edl


def _write_concat(concat_path: str, file_path: str, segments: list):
    with open(concat_path, "w") as f:
        f.write("ffconcat version 1.0\n")
        for seg in segments:
            f.write(f"file '{file_path}'\n")
            f.write(f"inpoint {seg['start_ms'] / 1000:.3f}\n")
            f.write(f"outpoint {seg['end_ms'] / 1000:.3f}\n")


def _has_video(file_path: str) -> bool:
    r = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_type",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path,
        ],
        capture_output=True,
        text=True,
    )
    return r.stdout.strip() == "video"


def _run_ffmpeg(concat_path: str, output_path: str, file_path: str):
    if _has_video(file_path):
        codec_flags = ["-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart"]
    else:
        codec_flags = ["-vn", "-c:a", "aac"]

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_path,
        *codec_flags,
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"ffmpeg failed: {result.stderr[-500:]}")
