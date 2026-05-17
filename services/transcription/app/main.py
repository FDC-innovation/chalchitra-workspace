from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os

# Fix OpenBLAS deadlock on ARM/Apple Silicon BEFORE importing torch/whisper
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import torch
import whisper

app = FastAPI()

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Loading Whisper model on {device}...")
model = whisper.load_model(os.environ.get("WHISPER_MODEL", "base"), device=device)
print("Whisper model loaded.")


class TranscribeRequest(BaseModel):
    episode_id: str
    file_path: str


@app.get("/")
def health():
    return {"status": "transcription service running"}


@app.post("/transcribe")
def transcribe(req: TranscribeRequest):
    if not os.path.exists(req.file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {req.file_path}")

    result = model.transcribe(req.file_path, word_timestamps=True)

    words = []
    for segment in result.get("segments", []):
        for w in segment.get("words", []):
            words.append({
                "word": w["word"].strip(),
                "start": round(w["start"], 3),
                "end": round(w["end"], 3),
            })

    srt_lines = []
    for i, segment in enumerate(result.get("segments", []), 1):
        start = segment["start"]
        end = segment["end"]
        text = segment["text"].strip()
        srt_lines.append(
            f"{i}\n"
            f"{format_time(start)} --> {format_time(end)}\n"
            f"{text}\n"
        )
    srt = "\n".join(srt_lines)

    return {
        "episode_id": req.episode_id,
        "text": result["text"],
        "words": words,
        "srt": srt,
    }


def format_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"