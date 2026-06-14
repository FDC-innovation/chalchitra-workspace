import httpx
from app.logger import get_logger
from app.context_writer import write_context
from app.explainer_state import ExplainerState

logger = get_logger("explainer_render")


async def explainer_render_node(state: ExplainerState) -> dict:
    episode_id = state["episode_id"]
    broll_sections = state.get("broll_sections") or []
    logger.info(f"[{episode_id[:8]}] Starting render — {len(broll_sections)} sections")

    sections_payload = [
        {
            "section_id": s["section_id"],
            "title": s["title"],
            "audio_path": s["audio_path"],
            "srt_path": s.get("srt_path"),
            "broll_path": s.get("broll_path"),
            "duration_seconds": s.get("audio_duration", s.get("duration_seconds", 10)),
            "avatar_image": state.get("avatar_image"),
        }
        for s in broll_sections
    ]

    async with httpx.AsyncClient(timeout=600) as client:
        # Render sections
        response = await client.post(
            "http://explainer_renderer:8017/render_section",
            json={
                "episode_id": episode_id,
                "sections": sections_payload,
                "avatar_image": state.get("avatar_image"),
                "output_title": state.get("script_title", "explainer"),
            },
        )
        response.raise_for_status()
        render_data = response.json()

        rendered = render_data.get("rendered", [])
        failed = render_data.get("failed", [])

        if not rendered:
            raise RuntimeError("No sections rendered successfully")

        # Stitch all sections
        section_paths = [r["rendered_path"] for r in rendered]
        stitch_response = await client.post(
            "http://explainer_renderer:8017/stitch",
            json={
                "episode_id": episode_id,
                "section_paths": section_paths,
                "output_title": state.get("script_title", "explainer_final"),
            },
        )
        stitch_response.raise_for_status()
        stitch_data = stitch_response.json()

    write_context(episode_id, "explainer_render", {
        "rendered_count": len(rendered),
        "failed_count": len(failed),
        "final_video": stitch_data.get("final_video"),
    })

    logger.info(f"[{episode_id[:8]}] Render done → {stitch_data.get('final_video')}")
    return {
        "rendered_sections": rendered,
        "failed_sections": failed,
        "final_video": stitch_data.get("final_video"),
        "pipeline_status": "completed",
    }
