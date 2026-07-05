from app.logger import get_logger
from app.context_writer import write_context
import httpx
from app.state import ChalchitraState

logger = get_logger("detect")


async def detect_node(state: ChalchitraState) -> dict:
    logger.info(f"[{state['episode_id'][:8]}] Starting detect")
    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "episode_id": state["episode_id"],
                "transcript": state["transcript_text"],
                "srt": state["srt"],
                "words": state.get("words") or [],
                "system_prompt": state.get("detect_prompt") or state.get("custom_prompt"),
            }
            response = await client.post("http://detect:8003/detect", json=payload, timeout=36000)
            response.raise_for_status()
            data = response.json()

        clips = data.get("clips", [])
        write_context(state["episode_id"], "detect", {
            "detected_clips_count": len(clips),
            "clips": [f"{c.get('title')} ({c.get('start_seconds')}s-{c.get('end_seconds')}s)" for c in clips],
        })
        logger.info(f"[{state['episode_id'][:8]}] Detect done — {len(clips)} clips")
        return {"detected_clips": clips}

    except Exception as e:
        logger.error(f"[{state['episode_id'][:8]}] Detect failed: {e}")
        raise
