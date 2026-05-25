import httpx
from app.state import ChalchitraState


async def detect_node(state: ChalchitraState) -> dict:
    # Check if transcript and srt are available; skip if not (resume case)
    if not state.get("transcript_text"):
        return {
            "detected_clips": [],
        }
    
    async with httpx.AsyncClient(timeout=1200.0) as client:
        payload = {
            "episode_id": state["episode_id"],
            "transcript": state.get("transcript_text") or "",
            "srt": state.get("srt") or "",
        }
        if state.get("detect_prompt"):
            payload["system_prompt"] = state["detect_prompt"]
        response = await client.post("http://detect:8003/detect", json=payload)
        response.raise_for_status()
        data = response.json()

    return {
        "detected_clips": data.get("clips", []),
    }
