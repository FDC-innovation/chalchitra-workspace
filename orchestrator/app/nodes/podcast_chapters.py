import json
import os
import re
import httpx
from app.logger import get_logger
from app.context_writer import write_context
from app.podcast_state import PodcastState

logger = get_logger("podcast_chapters")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://172.19.0.1:11434") + "/api/generate"


async def get_video_duration(file_path: str) -> float:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://ffmpeg:8004/duration",
                json={"file_path": file_path},
                timeout=36000,
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

    transcript = state["transcript_text"]
    words = transcript.split()
    if len(words) > 3000:
        logger.info(f"[{episode_id[:8]}] Truncating transcript from {len(words)} to 3000 words")
        transcript = " ".join(words[:3000])

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
        f"TRANSCRIPT:\n{transcript}"
    )

    async with httpx.AsyncClient(timeout=36000) as client:
        response = await client.post(
            OLLAMA_URL,
            json={
                "model": "llama3.2:latest",
                "prompt": prompt,
                "stream": False,
            },
        )
        response.raise_for_status()
        raw = response.json()["response"].strip()

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
