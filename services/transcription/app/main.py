from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
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
    try:
        result = model.transcribe(req.file_path, fp16=False, word_timestamps=False)
    except Exception as e:
        print(f"Transcribe error: {e}, retrying without timestamps...")
        try:
            result = model.transcribe(req.file_path, fp16=False, word_timestamps=False, condition_on_previous_text=False)
        except Exception as e2:
            raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e2)}")

    srt_lines = []
    for i, segment in enumerate(result.get("segments", []), 1):
        start = segment["start"]
        end = segment["end"]
        text = segment["text"].strip()
        srt_lines.append(f"{i}\n{format_time(start)} --> {format_time(end)}\n{text}\n")

    return {
        "episode_id": req.episode_id,
        "text": result["text"],
        "words": [],
        "srt": "\n".join(srt_lines),
    }

def format_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"
