import httpx
from app.state import ChalchitraState

async def transcribe_node(state: ChalchitraState) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://transcription:8001/transcribe",
            json={"episode_id": state["episode_id"], "file_path": state["file_path"]},
            timeout=None,
        )
        response.raise_for_status()
        data = response.json()

    # Log what we actually got back so we can verify
    import logging
    logging.getLogger("orchestrator").info(f"[transcribe] response keys: {list(data.keys())}")

    return {
        "transcript_text": data.get("text") or data.get("transcript") or data.get("transcript_text"),
        "srt": data.get("srt"),
        "words": data.get("words"),
    }
