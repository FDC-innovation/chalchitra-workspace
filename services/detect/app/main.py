from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import anthropic
import os
import json

app = FastAPI()
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))


class DetectRequest(BaseModel):
    episode_id: str
    transcript: str
    srt: Optional[str] = ""


@app.get("/")
def health():
    return {"status": "detect service running"}


@app.post("/detect")
def detect(req: DetectRequest):
    if not req.transcript.strip():
        raise HTTPException(400, "Empty transcript")

    word_count = len(req.transcript.split())
    estimated_duration = word_count / 2.5

    prompt = f"""You are an expert viral short-form video editor for Instagram Reels and TikTok.

Analyze this transcript (estimated duration: {estimated_duration:.0f} seconds) and find the best clips.

Transcript:
{req.transcript[:6000]}

RULES:
- Each clip must be 20-90 seconds long
- Pick 2-4 clips maximum
- Each clip must make sense on its own
- Start each clip at a natural sentence beginning
- Prioritize: surprising facts, strong opinions, emotional moments, actionable tips
- If the video is short (under 2 minutes), just pick 1-2 clips
- Clips must not overlap

Return ONLY valid JSON, no markdown, no explanation:
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

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )

    text = message.content[0].text.strip()

    if "```" in text:
        parts = text.split("```")
        for part in parts:
            if "{" in part:
                text = part
                if text.startswith("json"):
                    text = text[4:]
                break
    text = text.strip()

    try:
        data = json.loads(text)
        clips = data.get("clips", [])
    except Exception:
        raise HTTPException(500, f"Failed to parse Claude response: {text[:300]}")

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
                "title": "Key Insight",
                "start_seconds": 0,
                "end_seconds": clip_end,
                "reason": "Best available segment",
            })

    if not valid_clips:
        raise HTTPException(500, "Video too short to create clips (minimum 15 seconds needed)")

    valid_clips = valid_clips[:4]

    return {
        "episode_id": req.episode_id,
        "clips": valid_clips,
        "total_clips": len(valid_clips),
    }