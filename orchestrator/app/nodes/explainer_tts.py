import httpx
import asyncio
from app.logger import get_logger
from app.context_writer import write_context
from app.explainer_state import ExplainerState

logger = get_logger("explainer_tts")


async def explainer_tts_node(state: ExplainerState) -> dict:
    episode_id = state["episode_id"]
    sections = state.get("sections") or []
    logger.info(f"[{episode_id[:8]}] Starting TTS — {len(sections)} sections")

    tts_sections = []
    failed = []

    async with httpx.AsyncClient(timeout=120) as client:
        for section in sections:
            try:
                response = await client.post(
                    "http://tts:8014/synthesize",
                    json={
                        "episode_id": episode_id,
                        "text": section["narration"],
                        "section_id": section["section_id"],
                        "voice": "en-US-AndrewNeural",
                    },
                )
                response.raise_for_status()
                tts_data = response.json()
                tts_sections.append({
                    **section,
                    "audio_path": tts_data["audio_path"],
                    "srt_path": tts_data["srt_path"],
                    "audio_duration": tts_data["duration_seconds"],
                })
            except Exception as e:
                logger.error(f"[{episode_id[:8]}] TTS failed for section {section['section_id']}: {e}")
                failed.append({"section_id": section["section_id"], "error": str(e)})

    write_context(episode_id, "explainer_tts", {
        "tts_done": len(tts_sections),
        "failed": len(failed),
    })

    logger.info(f"[{episode_id[:8]}] TTS done — {len(tts_sections)} sections")
    return {"tts_sections": tts_sections}
