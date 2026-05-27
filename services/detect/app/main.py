from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from groq import Groq
import json
import re
import os

app = FastAPI()
client = Groq(api_key=os.environ["GROQ_API_KEY"])

MIN_CLIPS = 2


class DetectRequest(BaseModel):
    episode_id: str
    transcript: str
    srt: str = ""


def _extract_json(raw: str) -> list:
    """Parse JSON array from LLM output, stripping markdown code fences if present."""
    raw = raw.strip()
    # Strip ```json ... ``` or ``` ... ``` wrappers
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
    if match:
        raw = match.group(1).strip()
    # Find the outermost JSON array
    start = raw.find("[")
    end   = raw.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("No JSON array found in response")
    return json.loads(raw[start:end+1])


def _validate_clip(c: dict) -> bool:
    return (
        isinstance(c.get("title"), str) and c["title"].strip() and
        isinstance(c.get("start_seconds"), (int, float)) and
        isinstance(c.get("end_seconds"),   (int, float)) and
        c["end_seconds"] > c["start_seconds"]
    )


@app.get("/")
def health():
    return {"status": "detect service running"}


@app.post("/detect")
def detect(req: DetectRequest):
    if not req.transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript is empty")

    content = req.srt if req.srt.strip() else req.transcript

    prompt = f"""You are a viral clip detector for podcasts.

Given this transcript/SRT content, find EXACTLY 3 short clips (30-90 seconds each) that would perform well as standalone social media videos.

Return ONLY a JSON array of exactly 3 clip objects. Each object must have:
- title: short punchy clip title (string)
- start_seconds: clip start time in seconds (number)
- end_seconds: clip end time in seconds (number)
- reason: one sentence why this clip is engaging (string)

Rules:
- Each clip must be between 30 and 90 seconds long (end_seconds - start_seconds)
- Clips must not overlap each other
- Use actual timestamps from the content

Content:
{content[:6000]}

Return ONLY a valid JSON array, no markdown, no backticks, no explanation."""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        clips = _extract_json(raw)
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=500, detail=f"LLM returned invalid JSON: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Detect failed: {str(e)}")

    # Filter to valid clips only, keep up to 3
    valid = [c for c in clips if _validate_clip(c)][:3]

    if len(valid) < MIN_CLIPS:
        raise HTTPException(
            status_code=500,
            detail=f"LLM only returned {len(valid)} valid clip(s), need at least {MIN_CLIPS}",
        )

    return {
        "episode_id": req.episode_id,
        "clips": valid,
    }
