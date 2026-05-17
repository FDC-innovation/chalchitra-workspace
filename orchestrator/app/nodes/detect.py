import httpx
from app.state import ChalchitraState


async def detect_node(state: ChalchitraState) -> dict:
    async with httpx.AsyncClient() as client:
        payload = {
            "episode_id": state["episode_id"],
            "transcript": state["transcript_text"],
            "srt": state["srt"],
        }
        if state.get("detect_prompt"):
            payload["system_prompt"] = state["detect_prompt"]
        response = await client.post("http://detect:8003/detect", json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()

    return {
        "detected_clips": data.get("clips", []),
    }
