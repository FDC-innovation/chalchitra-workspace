import httpx
from app.state import ChalchitraState

async def enrich_node(state: ChalchitraState) -> dict:
    async with httpx.AsyncClient(timeout=60) as client:
        payload = {
            "episode_id": state["episode_id"],
            "transcript": state["transcript_text"],
        }
        if state.get("enrich_prompt"):
            payload["system_prompt"] = state["enrich_prompt"]
        response = await client.post("http://enrich:8002/enrich", json=payload)
        response.raise_for_status()
        data = response.json()

    enrichment = data.get("enrichment", {})
    return {
        "title": enrichment.get("title"),
        "show_notes": enrichment.get("show_notes"),
        "tags": enrichment.get("tags"),
        "chapters": enrichment.get("chapters"),
    }
