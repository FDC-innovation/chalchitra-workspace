import json
import os
import re
import httpx
from app.logger import get_logger
from app.context_writer import write_context
from app.podcast_state import PodcastState

logger = get_logger("podcast_chapters")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

DEFAULT_PROMPT = (
    "You are a podcast editor. Given the transcript below, identify 4-8 major chapters "
    "covering distinct topics. For each chapter return:\n"
    "- title: short punchy chapter title (max 6 words)\n"
    "- subtitle: one sentence describing what this chapter covers\n"
    "- start_seconds: float\n"
    "- end_seconds: float\n\n"
    "Return ONLY a raw JSON array. No markdown, no backticks, no explanation."
)


async def get_video_duration(file_path: str) -> float:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://ffmpeg:8004/duration",
                json={"file_path": file_path},
                timeout=30,
            )
            if response.status_code == 200:
                return float(response.json().get("duration", 99999))
    except Exception:
        pass
    return 99999


async def podcast_chapters_node(state: PodcastState) -> dict:
    episode_id = state["episode_id"]
    logger.info(f"[{episode_id[:8]}] Starting podcast_chapters")

    duration = await get_video_duration(state["file_path"])
    logger.info(f"[{episode_id[:8]}] Video duration: {duration:.1f}s")

    # Use human-edited prompt if provided, else default
    base_prompt = state.get("chapters_prompt") or DEFAULT_PROMPT

    prompt = (
        f"{base_prompt}\n\n"
        f"The video is exactly {duration:.0f} seconds long. "
        f"All timestamps must be between 0 and {duration:.0f}.\n\n"
        f"TRANSCRIPT:\n{state['transcript_text']}"
    )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
            },
            timeout=60,
        )
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"].strip()

    raw = re.sub(r"^```(?:json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()

    chapters = json.loads(raw)

    for c in chapters:
        c["start_seconds"] = min(float(c.get("start_seconds", 0)), duration)
        c["end_seconds"] = min(float(c.get("end_seconds", 0)), duration)

    chapters = [c for c in chapters if c["end_seconds"] > c["start_seconds"] + 5]

    write_context(episode_id, "podcast_chapters", {
        "chapters_count": len(chapters),
        "chapters": [
            f"{c.get('title')} ({c.get('start_seconds')}s–{c.get('end_seconds')}s)"
            for c in chapters
        ],
    })

    logger.info(f"[{episode_id[:8]}] podcast_chapters done — {len(chapters)} chapters")
    return {"chapters": chapters}