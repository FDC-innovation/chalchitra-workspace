import httpx
import json
import re
from app.state import ChalchitraState

async def enrich_node(state: ChalchitraState) -> dict:
    async with httpx.AsyncClient(timeout=1200.0) as client:
        payload = {
            "episode_id": state["episode_id"],
            "transcript": state["transcript_text"],
        }
        if state.get("enrich_prompt"):
            payload["system_prompt"] = state["enrich_prompt"]
        response = await client.post("http://enrich:8002/enrich", json=payload)
        response.raise_for_status()
        data = response.json()

    # Response is nested: data.enrichment.raw = "```json\n{...}\n```"
    raw = data.get("enrichment", {}).get("raw", "")
    
    # Strip markdown code fences if present
    clean = re.sub(r"```json\s*|\s*```", "", raw).strip()
    
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        parsed = {}

    return {
        "title": parsed.get("title"),
        "show_notes": parsed.get("topic") or parsed.get("show_notes"),
        "tags": parsed.get("key_points") or parsed.get("tags"),
        "chapters": parsed.get("chapters"),
    }
