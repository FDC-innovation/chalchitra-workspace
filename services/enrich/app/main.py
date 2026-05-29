from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from groq import Groq
import os
import json

app = FastAPI()
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))


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

    system = "You are a viral social media content strategist. Return ONLY valid JSON, no markdown, no explanation."
    prompt = req.system_prompt or f"""Given this transcript, extract metadata to help create viral short-form clips.

Transcript:
{req.transcript[:4000]}

Return ONLY valid JSON:
{{
  "title": "catchy overall title for the content",
  "show_notes": "2-3 sentence summary",
  "tags": ["tag1", "tag2", "tag3"],
  "chapters": [{{"title": "chapter title", "start_time": "0:00", "summary": "brief summary"}}]
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
    except Exception:
        data = {"title": "Episode", "show_notes": text, "tags": [], "chapters": []}

    return {"episode_id": req.episode_id, "enrichment": data}
