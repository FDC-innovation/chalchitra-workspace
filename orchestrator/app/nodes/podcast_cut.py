import httpx
from app.logger import get_logger
from app.context_writer import write_context
from app.podcast_state import PodcastState

logger = get_logger("podcast_cut")

MIN_CHAPTER_SECONDS = 5.0   # drop chapters shorter than this


async def podcast_cut_node(state: PodcastState) -> dict:
    episode_id = state["episode_id"]
    chapters = state.get("chapters") or []
    logger.info(f"[{episode_id[:8]}] Starting podcast_cut — {len(chapters)} chapters")

    chapter_clips = []

    for i, chapter in enumerate(chapters):
        start = chapter.get("start_seconds", 0)
        end = chapter.get("end_seconds", 0)
        duration = end - start

        if duration < MIN_CHAPTER_SECONDS:
            logger.warning(
                f"[{episode_id[:8]}] Skipping chapter '{chapter.get('title')}' "
                f"— too short ({duration:.1f}s)"
            )
            continue

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://ffmpeg:8004/ffmpeg",
                    json={
                        "episode_id": episode_id,
                        "file_path": state["file_path"],
                        "clips": [{
                            "title": chapter.get("title", f"Chapter_{i+1}"),
                            "start_seconds": start,
                            "end_seconds": end,
                        }],
                        "clip_index": i,
                    },
                    timeout=36000,
                )

            if response.status_code == 200:
                data = response.json()
                raw_clips = data.get("clips", [])
                if raw_clips:
                    clip = raw_clips[0]
                    # Carry subtitle forward for the card renderer
                    clip["subtitle"] = chapter.get("subtitle", "")
                    clip["chapter_index"] = i
                    chapter_clips.append(clip)
            else:
                logger.warning(
                    f"[{episode_id[:8]}] FFmpeg skipped chapter '{chapter.get('title')}': "
                    f"HTTP {response.status_code}"
                )

        except Exception as e:
            logger.error(
                f"[{episode_id[:8]}] FFmpeg error for chapter '{chapter.get('title')}': {e}"
            )

    write_context(episode_id, "podcast_cut", {
        "chapters_cut": len(chapter_clips),
        "files": [c.get("file_path", "") for c in chapter_clips],
    })

    logger.info(f"[{episode_id[:8]}] podcast_cut done — {len(chapter_clips)} segments cut")
    return {"chapter_clips": chapter_clips}