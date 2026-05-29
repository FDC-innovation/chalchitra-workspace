from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from groq import Groq
import os
import json

app = FastAPI()
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

class DetectRequest(BaseModel):
    episode_id: str
    transcript: str
    srt: Optional[str] = ""
    system_prompt: Optional[str] = None

@app.get("/")
def health():
    return {"status": "detect service running"}

@app.post("/detect")
def detect(req: DetectRequest):
    if not req.transcript.strip():
        raise HTTPException(400, "Empty transcript")

    word_count = len(req.transcript.split())
    estimated_duration = word_count / 2.5

    system = "You are a viral short-form video editor. Return ONLY valid JSON, no markdown, no explanation."
    prompt = req.system_prompt or f"""Analyze this transcript (estimated duration: {estimated_duration:.0f} seconds) and find the best clips.

Transcript:
{req.transcript[:6000]}

Rules:
- Each clip must be 20-90 seconds long
- Pick 2-4 clips maximum
- Clips must not overlap
- If video is short (under 2 min), pick 1-2 clips

Return ONLY valid JSON:
{{
  "clips": [
    {{
      "title": "punchy title max 6 words",
      "start_seconds": 0,
      "end_seconds": 45,
      "reason": "why this works as a clip"
    }}
  ]
}}"""

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        max_tokens=1000
    )

    text = response.choices[0].message.content.strip()
    text = text.replace('```json', '').replace('```', '').strip()

    try:
        data = json.loads(text)
        clips = data.get("clips", [])
    except Exception:
        clips = []

    valid_clips = []
    for clip in clips:
        start = float(clip.get("start_seconds", 0))
        end = float(clip.get("end_seconds", 0))
        duration = end - start
        if 15 <= duration <= 90:
            valid_clips.append({
                "title": clip.get("title", f"Clip {len(valid_clips)+1}"),
                "start_seconds": start,
                "end_seconds": min(end, estimated_duration),
                "reason": clip.get("reason", ""),
            })

    if not valid_clips:
        clip_end = min(60, estimated_duration)
        if clip_end >= 15:
            valid_clips.append({
                "title": "Key Moment",
                "start_seconds": 0,
                "end_seconds": clip_end,
                "reason": "Best available segment",
            })

    if not valid_clips:
        raise HTTPException(500, "Video too short to create clips")

    return {
        "episode_id": req.episode_id,
        "clips": valid_clips[:4],
        "total_clips": len(valid_clips[:4]),
    }
