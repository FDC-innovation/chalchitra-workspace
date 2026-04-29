from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import anthropic
import json
import os

app = FastAPI()
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


class DetectRequest(BaseModel):
    episode_id: str
    transcript: str
    srt: str = ""


@app.get("/")
def health():
    return {"status": "detect service running"}


@app.post("/detect")
def detect(req: DetectRequest):
    if not req.transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript is empty")

    content = req.srt if req.srt.strip() else req.transcript

    prompt = f"""You are a viral clip detector for podcasts.

Given this transcript/SRT content, find the 3 best short clips (30-90 seconds each).
Return ONLY a JSON array of clip objects with these fields:
- title: short punchy clip title (string)
- start_seconds: clip start time in seconds (number)
- end_seconds: clip end time in seconds (number)
- reason: one sentence why this clip is engaging (string)

Content:
{content[:6000]}

Return ONLY a valid JSON array. No explanation, no markdown, no backticks."""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        clips = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="LLM returned invalid JSON")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Detect failed: {str(e)}")

    return {
        "episode_id": req.episode_id,
        "clips": clips,
    }