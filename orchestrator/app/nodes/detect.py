import httpx
from app.state import ChalchitraState


async def detect_node(state: ChalchitraState) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://detect:8003/detect",
            json={
                "episode_id": state["episode_id"],
                "transcript": state["transcript_text"],
                "srt": state["srt"],
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()

    return {
        "detected_clips": data.get("clips", []),
    }
