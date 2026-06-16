from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import os
import json
import httpx

app = FastAPI()

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://172.19.0.1:11434") + "/api/generate"
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:latest")


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

    custom_context = f"\nUser instruction: {req.system_prompt}\n" if req.system_prompt else ""
    prompt = f"""You are a social media content strategist. Given this transcript, extract metadata to help create viral short-form clips.{custom_context}

Transcript:
{req.transcript[:4000]}

Return ONLY valid JSON, no markdown, no explanation:
{{
  "title": "catchy overall title for the content",
  "show_notes": "2-3 sentence summary",
  "tags": ["tag1", "tag2", "tag3"],
  "chapters": [{{"title": "chapter title", "start_time": "0:00", "summary": "brief summary"}}]
}}"""

    try:
        response = httpx.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120,
        )
        response.raise_for_status()
        text = response.json()["response"].strip()
    except Exception as e:
        raise HTTPException(500, f"Ollama request failed: {e}")

    text = text.replace('```json', '').replace('```', '').strip()
    try:
        data = json.loads(text)
    except Exception:
        data = {"title": "Episode", "show_notes": text, "tags": [], "chapters": []}

    return {"episode_id": req.episode_id, "enrichment": data}
