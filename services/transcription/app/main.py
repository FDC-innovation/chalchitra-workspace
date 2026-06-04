from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import whisper

app = FastAPI()

print("Loading Whisper model...", flush=True)
model = whisper.load_model("small")
print("Whisper model loaded.", flush=True)


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

    print(f"Transcribing: {req.file_path}", flush=True)

    # Detect language first
    audio = whisper.load_audio(req.file_path)
    audio = whisper.pad_or_trim(audio)
    mel = whisper.log_mel_spectrogram(audio).to(model.device)
    _, probs = model.detect_language(mel)
    detected_lang = max(probs, key=probs.get)
    print(f"Detected language: {detected_lang}", flush=True)

    # Translate to English regardless of source language
    result = model.transcribe(
        req.file_path,
        task="translate",
        word_timestamps=True,
        fp16=False,
        condition_on_previous_text=False,
        temperature=0,
    )

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
        srt_lines.append(
            f"{i}\n{format_time(segment['start'])} --> {format_time(segment['end'])}\n{segment['text'].strip()}\n"
        )

    print(f"Done. {len(words)} words. Lang: {detected_lang}", flush=True)

    return {
        "episode_id": req.episode_id,
        "text": result["text"],
        "words": words,
        "srt": "\n".join(srt_lines),
    }


def format_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"
