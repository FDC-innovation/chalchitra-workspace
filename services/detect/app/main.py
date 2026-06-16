from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Tuple
from groq import Groq
import os
import json
import re

app = FastAPI()
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

class DetectRequest(BaseModel):
    episode_id: str
    transcript: str
    srt: Optional[str] = ""
    system_prompt: Optional[str] = None

def parse_duration_range(text: str) -> Tuple[Optional[float], Optional[float]]:
    """Extract min/max seconds from phrases like '90-120 seconds' or '1-2 minutes'."""
    # "90-120 seconds" or "90s-120s"
    m = re.search(r'(\d+)\s*[-–to]+\s*(\d+)\s*s(?:ec(?:onds?)?)?', text, re.I)
    if m:
        return float(m.group(1)), float(m.group(2))
    # "1-2 minutes"
    m = re.search(r'(\d+(?:\.\d+)?)\s*[-–to]+\s*(\d+(?:\.\d+)?)\s*min(?:utes?)?', text, re.I)
    if m:
        return float(m.group(1)) * 60, float(m.group(2)) * 60
    # single "90 seconds"
    m = re.search(r'(\d+)\s*s(?:ec(?:onds?)?)', text, re.I)
    if m:
        v = float(m.group(1))
        return v * 0.8, v * 1.2
    # single "2 minutes"
    m = re.search(r'(\d+(?:\.\d+)?)\s*min(?:utes?)?', text, re.I)
    if m:
        v = float(m.group(1)) * 60
        return v * 0.8, v * 1.2
    return None, None


@app.get("/")
def health():
    return {"status": "detect service running"}

@app.post("/detect")
def detect(req: DetectRequest):
    if not req.transcript.strip():
        raise HTTPException(400, "Empty transcript")

    word_count = len(req.transcript.split())
    estimated_duration = word_count / 2.5

    system = "You are a professional video editor. Return ONLY valid JSON, no markdown, no explanation."

    user_min, user_max = (None, None)
    if req.system_prompt:
        user_min, user_max = parse_duration_range(req.system_prompt)

    if req.system_prompt:
        dur_hint = ""
        if user_min and user_max:
            dur_hint = f"\nIMPORTANT: Every clip MUST be between {user_min:.0f} and {user_max:.0f} seconds long. Do NOT return clips shorter or longer than this range."
        prompt = f"""Analyze this transcript (estimated duration: {estimated_duration:.0f} seconds) and find clips.

USER INSTRUCTIONS (follow exactly):
{req.system_prompt}{dur_hint}

Transcript:
{req.transcript[:6000]}

Return ONLY valid JSON — use actual timestamps from the transcript, not placeholder values:
{{
  "clips": [
    {{
      "title": "punchy title max 6 words",
      "start_seconds": <actual start>,
      "end_seconds": <actual end>,
      "reason": "why this works as a clip"
    }}
  ]
}}"""
    else:
        prompt = f"""Analyze this transcript (estimated duration: {estimated_duration:.0f} seconds) and find the best clips.

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

    # Use parsed duration range if found, else loose custom or strict default
    if user_min and user_max:
        min_dur, max_dur = user_min * 0.85, user_max * 1.15  # 15% tolerance
    elif req.system_prompt:
        min_dur, max_dur = 5, estimated_duration
    else:
        min_dur, max_dur = 15, 90

    valid_clips = []
    for clip in clips:
        start = float(clip.get("start_seconds", 0))
        end = float(clip.get("end_seconds", 0))
        duration = end - start
        if min_dur <= duration <= max_dur:
            valid_clips.append({
                "title": clip.get("title", f"Clip {len(valid_clips)+1}"),
                "start_seconds": start,
                "end_seconds": min(end, estimated_duration),
                "reason": clip.get("reason", ""),
            })

    if not valid_clips:
        clip_end = min(60, estimated_duration)
        if clip_end >= 5:
            valid_clips.append({
                "title": "Key Moment",
                "start_seconds": 0,
                "end_seconds": clip_end,
                "reason": "Best available segment",
            })

    if not valid_clips:
        raise HTTPException(500, "Video too short to create clips")

    # Respect count from user prompt; default caps at 4
    max_clips = len(valid_clips) if req.system_prompt else 4

    return {
        "episode_id": req.episode_id,
        "clips": valid_clips[:max_clips],
        "total_clips": len(valid_clips[:max_clips]),
    }
