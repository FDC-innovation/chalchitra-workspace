from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from faster_whisper import WhisperModel
import os

app = FastAPI()

print("Loading Whisper medium model...", flush=True)
model = WhisperModel("small", device="cpu", compute_type="int8")
print("Model loaded.", flush=True)

class TranscribeRequest(BaseModel):
    episode_id: str
    file_path: str

@app.get("/")
def health():
    return {"status": "ok"}

@app.post("/transcribe")
def transcribe(req: TranscribeRequest):
    if not os.path.exists(req.file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {req.file_path}")
    print(f"Transcribing: {req.file_path}", flush=True)
    segments, info = model.transcribe(req.file_path, language="hi", word_timestamps=True, beam_size=1, task="transcribe")
    words = []
    srt_lines = []
    full_text = []
    for i, seg in enumerate(segments, 1):
        full_text.append(seg.text.strip())
        srt_lines.append(f"{i}\n{fmt(seg.start)} --> {fmt(seg.end)}\n{seg.text.strip()}\n")
        for w in (seg.words or []):
            words.append({"word": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3)})
    print(f"Done. {len(words)} words.", flush=True)
    return {"episode_id": req.episode_id, "text": " ".join(full_text), "words": words, "srt": "\n".join(srt_lines)}

def fmt(s):
    h,m = int(s//3600), int((s%3600)//60)
    return f"{h:02}:{m:02}:{int(s%60):02},{int((s%1)*1000):03}"
