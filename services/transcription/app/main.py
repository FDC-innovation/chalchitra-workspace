from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import whisper
import threading
import os

app = FastAPI()
model = whisper.load_model("base")

# Whisper is not thread-safe — only one transcription at a time
_lock = threading.Semaphore(1)


class TranscribeRequest(BaseModel):
    file_path: str
    episode_id: str
    language: Optional[str] = None   # None = auto-detect
    task: str = "translate"          # "translate" → always outputs English


def _build_srt(segments: list) -> str:
    def fmt(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"
    lines = []
    for i, seg in enumerate(segments, start=1):
        lines.append(str(i))
        lines.append(f"{fmt(seg['start'])} --> {fmt(seg['end'])}")
        lines.append(seg["text"].strip())
        lines.append("")
    return "\n".join(lines)


@app.get("/")
def health():
    return {"status": "transcription service running"}


@app.post("/transcribe")
def transcribe(req: TranscribeRequest):
    if not os.path.exists(req.file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {req.file_path}")
    with _lock:
        try:
            kwargs = {"word_timestamps": True, "task": req.task}
            if req.language:
                kwargs["language"] = req.language
            result = model.transcribe(req.file_path, **kwargs)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Whisper failed: {str(e)}")

    segments = result.get("segments", [])
    words = []
    for seg in segments:
        for w in seg.get("words", []):
            words.append({"word": w["word"], "start": w["start"], "end": w["end"]})

    srt = _build_srt(segments)
    srt_path = os.path.splitext(req.file_path)[0] + ".srt"
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt)

    return {
        "episode_id": req.episode_id,
        "text": result["text"],
        "duration": segments[-1]["end"] if segments else 0,
        "words": words,
        "srt": srt,
        "srt_path": srt_path,
    }
