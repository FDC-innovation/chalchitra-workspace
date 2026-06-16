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


def parse_chapter_count(text: str):
    """Extract min/max chapter count from text like '2-3 chapters' or '4 chapters'."""
    m = re.search(r'(\d+)\s*[-–to]+\s*(\d+)\s*chapters?', text, re.I)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r'(\d+)\s*chapters?', text, re.I)
    if m:
        v = int(m.group(1))
        return v, v
    return None, None


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

    custom_prompt = state.get("custom_prompt") or ""
    min_ch, max_ch = parse_chapter_count(custom_prompt) if custom_prompt else (None, None)
    count_range = f"{min_ch}-{max_ch}" if min_ch and max_ch else "4-8"
    count_hint = f"\nCRITICAL: Return EXACTLY {min_ch} to {max_ch} chapters — no more, no fewer.\n" if min_ch else ""
    user_instruction = f"\nUser instruction: {custom_prompt}\n{count_hint}" if custom_prompt else ""

    prompt = (
        f"You are a podcast editor. The video is exactly {duration:.0f} seconds long.\n"
        f"Given the transcript below, identify {count_range} major chapters covering distinct topics.{user_instruction}\n"
        "For each chapter return:\n"
        "- title: short punchy chapter title (max 6 words)\n"
        "- subtitle: one sentence describing what this chapter covers\n"
        f"- start_seconds: use REAL timestamps from the transcript — NOT evenly spaced\n"
        f"- end_seconds: must equal the start_seconds of the NEXT chapter\n\n"
        "CRITICAL RULES:\n"
        "- Chapters must be CONTIGUOUS — no gaps between them\n"
        "- First chapter start_seconds = 0\n"
        f"- Last chapter end_seconds = {duration:.0f}\n"
        "- Base timestamps on when topics actually shift in the transcript\n"
        "- Do NOT invent evenly-spaced timestamps like 0,10,20,30\n\n"
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

    # Sort and force contiguous — end of each chapter = start of next
    chapters.sort(key=lambda c: float(c.get("start_seconds", 0)))
    for i in range(len(chapters) - 1):
        chapters[i]["end_seconds"] = chapters[i + 1]["start_seconds"]
    if chapters:
        chapters[0]["start_seconds"] = 0.0
        chapters[-1]["end_seconds"] = duration

    for c in chapters:
        c["start_seconds"] = round(min(float(c.get("start_seconds", 0)), duration), 2)
        c["end_seconds"] = round(min(float(c.get("end_seconds", 0)), duration), 2)

    chapters = [c for c in chapters if c["end_seconds"] > c["start_seconds"] + 5]

    # Enforce max chapter count from user prompt
    if max_ch and len(chapters) > max_ch:
        chapters = chapters[:max_ch]
        # Re-fix last chapter end after truncation
        if chapters:
            chapters[-1]["end_seconds"] = duration

    write_context(episode_id, "podcast_chapters", {
        "chapters_count": len(chapters),
        "chapters": [
            f"{c.get('title')} ({c.get('start_seconds')}s–{c.get('end_seconds')}s)"
            for c in chapters
        ],
    })

    logger.info(f"[{episode_id[:8]}] podcast_chapters done — {len(chapters)} chapters")
    return {"chapters": chapters}
