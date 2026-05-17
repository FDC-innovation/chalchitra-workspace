from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import anthropic
import os
import json

app = FastAPI()
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))


class EnrichRequest(BaseModel):
    episode_id: str
    transcript: str
    system_prompt: Optional[str] = None


@app.get("/")
def health():
    return {"status": "enrich service running"}


@app.post("/enrich")
def enrich(req: EnrichRequest):
    if not req.transcript.strip():
        raise HTTPException(400, "Empty transcript")

    prompt = req.system_prompt or f"""You are a viral social media content strategist.

Given this transcript, extract metadata to help create viral short-form clips.

Transcript:
{req.transcript[:4000]}

Return ONLY valid JSON (no markdown, no explanation):
{{
  "title": "catchy overall title for the content",
  "topic": "main topic in 3-5 words",
  "hook": "most compelling opening line or idea",
  "key_points": ["point 1", "point 2", "point 3"],
  "target_audience": "who this is for",
  "tone": "educational|motivational|entertaining|informational"
}}"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}]
    )

    text = message.content[0].text.strip()
    try:
        data = json.loads(text)
    except Exception:
        data = {"raw": text}

    return {
        "episode_id": req.episode_id,
        "enrichment": data,
    }
