import httpx
import json
import re
from app.state import ChalchitraState

async def enrich_node(state: ChalchitraState) -> dict:
    transcript = state.get("transcript_text", "")
    if not transcript:
        return {}

    async with httpx.AsyncClient(timeout=1200.0) as client:
        payload = {
            "episode_id": state["episode_id"],
            "transcript": transcript,
        }
        if state.get("enrich_prompt"):
            payload["system_prompt"] = state["enrich_prompt"]
        response = await client.post("http://enrich:8002/enrich", json=payload)
        response.raise_for_status()
        data = response.json()

    # enrichment is now a direct dict, not wrapped in raw
    enrichment = data.get("enrichment", {})
    
    # handle both old raw format and new direct format
    if isinstance(enrichment, dict) and "raw" in enrichment:
        raw = enrichment.get("raw", "")
        clean = re.sub(r"```json\s*|\s*```", "", raw).strip()
        try:
            enrichment = json.loads(clean)
        except json.JSONDecodeError:
            enrichment = {}

    return {
        "title": enrichment.get("title"),
        "show_notes": enrichment.get("show_notes") or enrichment.get("topic"),
        "tags": enrichment.get("tags") or enrichment.get("key_points"),
        "chapters": enrichment.get("chapters"),
    }