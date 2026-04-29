from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import anthropic
import json
import os

app = FastAPI()
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


class EnrichRequest(BaseModel):
    episode_id: str
    transcript: str


@app.get("/")
def health():
    return {"status": "enrich service running"}


@app.post("/enrich")
def enrich(req: EnrichRequest):
    if not req.transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript is empty")

    prompt = f"""You are a podcast metadata generator.

Given this transcript, return ONLY a JSON object with these fields:
- title: catchy episode title (string)
- show_notes: 2-3 sentence summary (string)
- tags: list of 5 relevant tags (array of strings)
- chapters: list of chapters, each with "title" and "start_time" in seconds (array of objects)

Transcript:
{req.transcript[:6000]}

Return ONLY valid JSON. No explanation, no markdown, no backticks."""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="LLM returned invalid JSON")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Enrich failed: {str(e)}")

    return {
        "episode_id": req.episode_id,
        "title": data.get("title"),
        "show_notes": data.get("show_notes"),
        "tags": data.get("tags", []),
        "chapters": data.get("chapters", []),
    }