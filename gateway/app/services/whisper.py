import httpx
import os

TRANSCRIPTION_URL = os.environ.get("TRANSCRIPTION_URL", "http://transcription:8001")

async def transcribe_file(file_path: str) -> dict:
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(f"{TRANSCRIPTION_URL}/transcribe", json={
            "episode_id": "internal",
            "file_path": str(file_path),
        })
        r.raise_for_status()
        return r.json()