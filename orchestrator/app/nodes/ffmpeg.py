import httpx
from app.state import ChalchitraState


async def ffmpeg_node(state: ChalchitraState) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://ffmpeg:8004/ffmpeg",
            json={
                "episode_id": state["episode_id"],
                "file_path": state["file_path"],
                "clips": state["detected_clips"],
            },
            timeout=300,
        )
        response.raise_for_status()
        data = response.json()

    return {
        "cut_clips": data.get("clips", []),
    }
