import httpx
from app.logger import get_logger
from app.context_writer import write_context
from app.explainer_state import ExplainerState

logger = get_logger("explainer_broll")


async def explainer_broll_node(state: ExplainerState) -> dict:
    episode_id = state["episode_id"]
    tts_sections = state.get("tts_sections") or []
    logger.info(f"[{episode_id[:8]}] Starting b-roll fetch — {len(tts_sections)} sections")

    sections_payload = [
        {
            "section_id": s["section_id"],
            "keywords": s.get("broll_keywords", [s["title"]]),
            "duration_seconds": s.get("audio_duration", s.get("duration_seconds", 10)),
        }
        for s in tts_sections
    ]

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            "http://broll:8016/fetch_batch",
            json={
                "episode_id": episode_id,
                "sections": sections_payload,
            },
        )
        response.raise_for_status()
        data = response.json()

    fetched = {b["section_id"]: b for b in data.get("fetched", [])}

    broll_sections = []
    for s in tts_sections:
        broll = fetched.get(s["section_id"])
        broll_sections.append({
            **s,
            "broll_path": broll["video_path"] if broll else None,
            "broll_keyword": broll["keyword_used"] if broll else None,
        })

    write_context(episode_id, "explainer_broll", {
        "fetched": len(fetched),
        "failed": len(data.get("failed", [])),
        "keywords_used": [b.get("keyword_used") for b in data.get("fetched", [])],
    })

    logger.info(f"[{episode_id[:8]}] B-roll done — {len(fetched)} fetched")
    return {"broll_sections": broll_sections}
