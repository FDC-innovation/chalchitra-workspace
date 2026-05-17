import os
import torch
import numpy as np
import librosa
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from resemblyzer import VoiceEncoder
from sklearn.cluster import KMeans

app = FastAPI()

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Loading VoiceEncoder on {device}", flush=True)
encoder = VoiceEncoder(device)
print("VoiceEncoder ready.", flush=True)


class DiarizeRequest(BaseModel):
    episode_id: str
    file_path: str
    num_speakers: int = 2


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/diarize")
def diarize(req: DiarizeRequest):
    if not os.path.exists(req.file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {req.file_path}")

    wav, _ = librosa.load(req.file_path, sr=16000, mono=True)

    window = int(1.5 * 16000)
    step = int(0.75 * 16000)

    embeddings = []
    timestamps = []
    for start in range(0, len(wav) - window, step):
        chunk = wav[start : start + window]
        embeddings.append(encoder.embed_utterance(chunk))
        timestamps.append(round(start / 16000, 3))

    if not embeddings:
        raise HTTPException(status_code=422, detail="Audio too short for diarization (minimum ~2 seconds)")

    n_clusters = min(req.num_speakers, len(embeddings))
    labels = KMeans(n_clusters=n_clusters, n_init=10, random_state=42).fit_predict(
        np.array(embeddings)
    )

    segments = []
    for i, (t, label) in enumerate(zip(timestamps, labels)):
        speaker = f"Speaker_{chr(65 + int(label))}"
        end_t = timestamps[i + 1] if i + 1 < len(timestamps) else round(t + 1.5, 3)
        if segments and segments[-1]["speaker"] == speaker:
            segments[-1]["end"] = end_t
        else:
            segments.append({"speaker": speaker, "start": t, "end": end_t})

    return {"episode_id": req.episode_id, "segments": segments}
