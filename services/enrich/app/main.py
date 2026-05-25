from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import anthropic
import httpx
import os
import json

app = FastAPI()
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

LLM_BACKEND = os.environ.get("LLM_BACKEND", "ollama")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:e2b")
OLLAMA_URL = "http://ollama:11434/api/generate"


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

    if LLM_BACKEND == "ollama":
        if req.system_prompt:
            prompt = (
                req.system_prompt +
                "\n\nReturn ONLY a JSON object with keys: title, show_notes, tags, chapters. "
                "No markdown, no backticks, just raw JSON.\n\n"
                f"Transcript: {req.transcript[:4000]}"
            )
        else:
            prompt = (
                "You are a podcast content expert. Given this transcript, return ONLY a JSON object with these exact keys: "
                "title (string), show_notes (string), tags (list of strings), chapters (list of objects with keys: title, start_time, summary). "
                "No markdown, no backticks, just raw JSON.\n\n"
                f"Transcript: {req.transcript[:4000]}"
            )

        try:
            resp = httpx.post(OLLAMA_URL, json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False
            }, timeout=1200.0)
            resp.raise_for_status()
            text = resp.json()["response"].strip()
        except Exception as e:
            raise HTTPException(500, f"Ollama request failed: {e}")

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
        except Exception:
            raise HTTPException(500, f"Failed to parse Ollama response as JSON: {text[:300]}")

        return {
            "episode_id": req.episode_id,
            "enrichment": data,
        }

    else:  # claude
        if req.system_prompt:
            prompt = (
                req.system_prompt +
                f"\n\nTranscript:\n{req.transcript[:4000]}\n\n"
                "Return ONLY valid JSON (no markdown, no explanation)."
            )
        else:
            prompt = f"""You are a viral social media content strategist.

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