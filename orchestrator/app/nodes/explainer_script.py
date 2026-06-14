import httpx
from app.logger import get_logger
from app.context_writer import write_context
from app.explainer_state import ExplainerState

logger = get_logger("explainer_script")


async def explainer_script_node(state: ExplainerState) -> dict:
    episode_id = state["episode_id"]
    logger.info(f"[{episode_id[:8]}] Starting script writing — topic: {state['topic']}")

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "http://script_writer:8013/write",
            json={
                "topic": state["topic"],
                "duration_minutes": state.get("duration_minutes", 3),
                "style": state.get("style", "professional"),
                "custom_prompt": state.get("script_prompt"),
            },
        )
        response.raise_for_status()
        data = response.json()

    sections = data.get("sections", [])
    write_context(episode_id, "explainer_script", {
        "title": data.get("title"),
        "sections_count": len(sections),
        "sections": [f"{s['title']} ({s.get('duration_seconds', 0)}s)" for s in sections],
    })

    logger.info(f"[{episode_id[:8]}] Script done — {len(sections)} sections")
    return {
        "script_title": data.get("title"),
        "sections": sections,
    }
