import re
import subprocess
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()


class DetectSilenceRequest(BaseModel):
    episode_id: str
    file_path: str
    min_silence_len_ms: int = 500
    silence_thresh_db: int = -40


class Segment(BaseModel):
    start_ms: int
    end_ms: int
    type: str


class DetectSilenceResponse(BaseModel):
    episode_id: str
    segments: List[Segment]
    speech_ratio: float


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/detect_silence", response_model=DetectSilenceResponse)
def detect_silence(req: DetectSilenceRequest):
    duration_s = _get_duration(req.file_path)
    min_duration_s = req.min_silence_len_ms / 1000.0

    silences = _run_silencedetect(req.file_path, req.silence_thresh_db, min_duration_s)
    segments = _build_segments(silences, duration_s)

    total_ms = int(duration_s * 1000)
    speech_ms = sum(s["end_ms"] - s["start_ms"] for s in segments if s["type"] == "speech")
    speech_ratio = round(speech_ms / total_ms, 4) if total_ms > 0 else 0.0

    return DetectSilenceResponse(
        episode_id=req.episode_id,
        segments=[Segment(**s) for s in segments],
        speech_ratio=speech_ratio,
    )


def _get_duration(file_path: str) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=422, detail=f"ffprobe failed: {result.stderr.strip()}")
    try:
        return float(result.stdout.strip())
    except ValueError:
        raise HTTPException(status_code=422, detail="Could not parse file duration")


def _run_silencedetect(file_path: str, thresh_db: int, min_duration_s: float) -> list:
    cmd = [
        "ffmpeg", "-i", file_path,
        "-af", f"silencedetect=noise={thresh_db}dB:d={min_duration_s}",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    # ffmpeg writes filter output to stderr even on success
    if result.returncode != 0 and "silencedetect" not in result.stderr:
        raise HTTPException(status_code=422, detail=f"ffmpeg failed: {result.stderr.strip()[:500]}")

    stderr = result.stderr
    starts = [float(m.group(1)) for m in re.finditer(r"silence_start: ([\d.e+\-]+)", stderr)]
    ends   = [float(m.group(1)) for m in re.finditer(r"silence_end: ([\d.e+\-]+)",   stderr)]

    silences = []
    for i, start in enumerate(starts):
        silences.append({
            "start_s": start,
            # if file ends mid-silence, ffmpeg may not emit silence_end
            "end_s": ends[i] if i < len(ends) else None,
        })
    return silences


def _build_segments(silences: list, duration_s: float) -> list:
    segments = []
    cursor = 0.0

    for silence in silences:
        s_start = silence["start_s"]
        s_end   = silence["end_s"] if silence["end_s"] is not None else duration_s

        if s_start > cursor:
            segments.append({
                "start_ms": _ms(cursor),
                "end_ms":   _ms(s_start),
                "type":     "speech",
            })

        segments.append({
            "start_ms": _ms(s_start),
            "end_ms":   _ms(s_end),
            "type":     "silence",
        })
        cursor = s_end

    if cursor < duration_s:
        segments.append({
            "start_ms": _ms(cursor),
            "end_ms":   _ms(duration_s),
            "type":     "speech",
        })

    return segments


def _ms(seconds: float) -> int:
    return int(seconds * 1000)
