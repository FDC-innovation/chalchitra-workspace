from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from groq import Groq
import os
import json

app = FastAPI()
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))


class ScriptRequest(BaseModel):
    topic: str
    duration_minutes: Optional[int] = 3
    style: Optional[str] = "professional"
    custom_prompt: Optional[str] = None


class ScriptSection(BaseModel):
    section_id: int
    title: str
    narration: str
    broll_keywords: List[str]
    duration_seconds: float


@app.get("/")
def health():
    return {"status": "script_writer running"}


@app.post("/write")
def write_script(req: ScriptRequest):
    if not req.topic.strip():
        raise HTTPException(400, "Topic is required")

    word_count = req.duration_minutes * 130

    prompt = req.custom_prompt or f"""You are a professional corporate explainer video scriptwriter.

Write a {req.duration_minutes}-minute explainer video script about: {req.topic}

Style: {req.style}
Target word count for narration: {word_count} words total

Rules:
- Split into 4-6 clear sections
- Each section has a title, narration text, and b-roll keywords
- Narration must be natural spoken language, no bullet points
- B-roll keywords are 2-3 word search terms for stock footage
- Keep each section 20-40 seconds of speaking time

Return ONLY valid JSON:
{{
  "title": "video title",
  "sections": [
    {{
      "section_id": 1,
      "title": "section title",
      "narration": "full narration text for this section",
      "broll_keywords": ["keyword1", "keyword2", "keyword3"],
      "duration_seconds": 30
    }}
  ]
}}"""

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": "You are a scriptwriter. Return ONLY valid JSON, no markdown, no explanation."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.4,
        max_tokens=2000
    )

    text = response.choices[0].message.content.strip()
    text = text.replace('```json', '').replace('```', '').strip()

    try:
        data = json.loads(text)
    except Exception:
        raise HTTPException(500, f"Failed to parse script JSON: {text[:200]}")

    return {
        "topic": req.topic,
        "title": data.get("title", req.topic),
        "sections": data.get("sections", []),
        "total_sections": len(data.get("sections", [])),
    }
