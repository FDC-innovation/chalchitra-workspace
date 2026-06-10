from app.logger import get_logger
from app.context_writer import write_context
import httpx
from app.state import ChalchitraState

logger = get_logger("ffmpeg")


async def ffmpeg_node(state: ChalchitraState) -> dict:
    logger.info(f"[{state['episode_id'][:8]}] Starting ffmpeg")
    cut_clips = []
    for i, clip in enumerate(state.get("detected_clips") or []):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://ffmpeg:8004/ffmpeg",
                    json={
                        "episode_id": state["episode_id"],
                        "file_path": state["file_path"],
                        "clips": [clip],
                        "clip_index": i,
                    },
                    timeout=36000,
                )
                if response.status_code == 200:
                    data = response.json()
                    cut_clips.extend(data.get("clips", []))
                else:
                    logger.warning(f"[{state['episode_id'][:8]}] FFmpeg skipped clip '{clip.get('title')}': {response.status_code}")
        except Exception as e:
            logger.error(f"[{state['episode_id'][:8]}] FFmpeg error for '{clip.get('title')}': {e}")

    write_context(state["episode_id"], "ffmpeg", {
        "clips_cut": len(cut_clips),
        "clips": [c.get("file_path", "") for c in cut_clips],
    })
    logger.info(f"[{state['episode_id'][:8]}] FFmpeg done — {len(cut_clips)} clips cut")
    return {"cut_clips": cut_clips}
