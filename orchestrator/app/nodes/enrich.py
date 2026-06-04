from app.logger import get_logger
from app.context_writer import write_context
import httpx
from app.state import ChalchitraState

logger = get_logger("enrich")


async def enrich_node(state: ChalchitraState) -> dict:
    logger.info(f"[{state['episode_id'][:8]}] Starting enrich")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            payload = {
                "episode_id": state["episode_id"],
                "transcript": state["transcript_text"],
            }
            # Use human-edited prompt if provided
            if state.get("enrich_prompt"):
                payload["system_prompt"] = state["enrich_prompt"]

            response = await client.post("http://enrich:8002/enrich", json=payload)
            response.raise_for_status()
            data = response.json()

        enrichment = data.get("enrichment", {})

        write_context(state["episode_id"], "enrich", {
            "title": enrichment.get("title"),
            "tags": enrichment.get("tags"),
            "show_notes": str(enrichment.get("show_notes", ""))[:200],
        })

        logger.info(f"[{state['episode_id'][:8]}] Enrich done — title: {enrichment.get('title')}")

        return {
            "title": enrichment.get("title"),
            "show_notes": enrichment.get("show_notes"),
            "tags": enrichment.get("tags"),
            "chapters": enrichment.get("chapters"),
        }

    except Exception as e:
        logger.error(f"[{state['episode_id'][:8]}] Enrich failed: {e}")
        raise