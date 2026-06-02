from app.logger import get_logger
from app.context_writer import write_context
import httpx
from app.state import ChalchitraState

logger = get_logger("transcribe")


async def transcribe_node(state: ChalchitraState) -> dict:
    logger.info(f"[{state['episode_id'][:8]}] Starting transcribe")
    try:
        engine = state.get("transcription_engine") or "whisper"
        urls = {
            "whisper": "http://transcription:8001/transcribe",
        }
        url = urls.get(engine, urls["whisper"])

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json={"episode_id": state["episode_id"], "file_path": state["file_path"]},
                timeout=None,
            )
            response.raise_for_status()
            data = response.json()

        # Save transcript as MD
        md_path = f"/app/shared/volumes/{state['episode_id']}_transcript.md"
        try:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(f"# Episode: {state['episode_id']}\n\n")
                f.write(f"## Words: {len(data.get('words', []))}\n\n")
                f.write(f"## Transcript\n\n{data.get('text', '')}\n\n")
                f.write(f"## SRT\n\n```\n{data.get('srt', '')}\n```\n")
        except Exception as e:
            logger.warning(f"MD save failed: {e}")

        write_context(state["episode_id"], "transcribe", {
            "words_count": len(data.get("words", [])),
            "transcript_preview": data.get("text", "")[:300],
        })

        logger.info(f"[{state['episode_id'][:8]}] Transcribe done — {len(data.get('words', []))} words")

        return {
            "transcript_text": data.get("text") or data.get("transcript") or data.get("transcript_text"),
            "srt": data.get("srt"),
            "words": data.get("words"),
        }

    except Exception as e:
        logger.error(f"[{state['episode_id'][:8]}] Transcribe failed: {e}")
        raise
