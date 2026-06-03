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


async def get_video_duration(file_path: str) -> float:
    """Get video duration using ffprobe via ffmpeg service."""
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

    # Get actual video duration to clamp timestamps
    duration = await get_video_duration(state["file_path"])
    logger.info(f"[{episode_id[:8]}] Video duration: {duration:.1f}s")

    word_count = len(state.get("words") or [])
    avg_words_per_sec = word_count / duration if duration > 0 else 3

    prompt = (
        f"You are a podcast editor. The video is exactly {duration:.0f} seconds long.\n"
        "Given the transcript below, identify 4-8 major chapters covering distinct topics.\n"
        "For each chapter return:\n"
        "- title: short punchy chapter title (max 6 words)\n"
        "- subtitle: one sentence describing what this chapter covers\n"
        f"- start_seconds: float between 0 and {duration:.0f}\n"
        f"- end_seconds: float between 0 and {duration:.0f}\n\n"
        "IMPORTANT: All timestamps must be within the video duration. "
        f"The last chapter must end at or before {duration:.0f} seconds.\n\n"
        "Return ONLY a raw JSON array. No markdown, no backticks, no explanation.\n\n"
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

    # Clamp all timestamps to actual video duration
    for c in chapters:
        c["start_seconds"] = min(float(c.get("start_seconds", 0)), duration)
        c["end_seconds"] = min(float(c.get("end_seconds", 0)), duration)

    # Drop invalid chapters
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
