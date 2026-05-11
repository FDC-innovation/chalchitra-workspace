import httpx
from app.state import ChalchitraState

async def renderer_node(state: ChalchitraState) -> dict:
    approved_clips = state.get("approved_clips") or []
    rendered_clips = []
    failed_clips = []

    async with httpx.AsyncClient() as client:
        for clip in approved_clips:
            try:
                response = await client.post(
                    "http://renderer:8006/render",
                    json={
                        "episode_id": state["episode_id"],
                        "clip_path": clip.get("file_path"),  # ✅ fixed
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
                failed_clips.append({**clip, "error": str(e)})

    return {
        "rendered_clips": rendered_clips,
        "failed_clips": failed_clips,
        "pipeline_status": "completed",
    }
