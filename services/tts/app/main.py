from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import os
import subprocess
import edge_tts

app = FastAPI()

SHARED = "/app/shared/volumes"
DEFAULT_VOICE = "en-US-AndrewNeural"


class TTSRequest(BaseModel):
    episode_id: str
    text: str
    section_id: Optional[int] = 0
    voice: Optional[str] = DEFAULT_VOICE


@app.get("/")
def health():
    return {"status": "tts running"}


def fmt_time(ms: int) -> str:
    h = ms // 3600000
    m = (ms % 3600000) // 60000
    s = (ms % 60000) // 1000
    ms_rem = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms_rem:03d}"


def boundaries_to_srt(boundaries: list) -> str:
    if not boundaries:
        return ""
    lines = []
    for idx, b in enumerate(boundaries, 1):
        start_ms = b["offset"] // 10000
        end_ms = (b["offset"] + b["duration"]) // 10000
        text = b["text"]
        lines.append(f"{idx}\n{fmt_time(start_ms)} --> {fmt_time(end_ms)}\n{text}\n")
    return "\n".join(lines)


@app.post("/synthesize")
async def synthesize(req: TTSRequest):
    if not req.text.strip():
        raise HTTPException(400, "Text is required")

    episode_dir = os.path.join(SHARED, req.episode_id)
    os.makedirs(episode_dir, exist_ok=True)

    audio_path = os.path.join(episode_dir, f"section_{req.section_id:02d}_audio.mp3")
    srt_path = os.path.join(episode_dir, f"section_{req.section_id:02d}_audio.srt")

    communicate = edge_tts.Communicate(req.text, req.voice)

    audio_chunks = []
    boundaries = []

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_chunks.append(chunk["data"])
        elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
            boundaries.append({
                "text": chunk.get("text", ""),
                "offset": chunk.get("offset", 0),
                "duration": chunk.get("duration", 0),
            })

    with open(audio_path, "wb") as f:
        for chunk in audio_chunks:
            f.write(chunk)

    srt_content = boundaries_to_srt(boundaries)
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", audio_path],
        capture_output=True, text=True
    )
    duration = float(probe.stdout.strip()) if probe.stdout.strip() else 0.0

    return {
        "episode_id": req.episode_id,
        "section_id": req.section_id,
        "audio_path": audio_path,
        "srt_path": srt_path,
        "duration_seconds": duration,
        "voice": req.voice,
        "words_count": len(boundaries),
        "has_captions": len(boundaries) > 0,
    }
