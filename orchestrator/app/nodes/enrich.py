import httpx
from app.state import ChalchitraState


async def enrich_node(state: ChalchitraState) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://enrich:8002/enrich",
            json={"episode_id": state["episode_id"], "transcript": state["transcript_text"]},
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()

    return {
        "title": data.get("title"),
        "show_notes": data.get("show_notes"),
        "tags": data.get("tags"),
        "chapters": data.get("chapters"),
    }
