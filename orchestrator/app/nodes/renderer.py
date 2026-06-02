from app.logger import get_logger
from app.context_writer import write_context
import httpx
from app.state import ChalchitraState

logger = get_logger("renderer")


async def renderer_node(state: ChalchitraState) -> dict:
    logger.info(f"[{state['episode_id'][:8]}] Starting renderer")
    clips_to_render = state.get("cut_clips") or []
    rendered_clips = []
    failed_clips = []

    async with httpx.AsyncClient() as client:
        for clip in clips_to_render:
            try:
                response = await client.post(
                    "http://renderer:8006/render",
                    json={
                        "episode_id": state["episode_id"],
                        "clip_path": clip.get("file_path"),
                        "title": clip.get("title"),
                        "start_seconds": clip.get("start_seconds"),
                        "end_seconds": clip.get("end_seconds"),
                        "words": state.get("words") or [],
                        "channel_name": "Chalchitra",
                        "cta_text": "Follow for more",
                    },
                    timeout=600,
                )
                response.raise_for_status()
                rendered_clips.append(response.json())
            except Exception as e:
                logger.error(f"[{state['episode_id'][:8]}] Render failed for '{clip.get('title')}': {e}")
                failed_clips.append({**clip, "error": str(e)})

    write_context(state["episode_id"], "renderer", {
        "rendered_count": len(rendered_clips),
        "failed_count": len(failed_clips),
        "output_files": [c.get("rendered_clip", "") for c in rendered_clips],
    })
    logger.info(f"[{state['episode_id'][:8]}] Renderer done — {len(rendered_clips)} rendered, {len(failed_clips)} failed")

    return {
        "rendered_clips": rendered_clips,
        "failed_clips": failed_clips,
        "pipeline_status": "completed",
    }
