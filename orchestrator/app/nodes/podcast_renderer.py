import httpx
from app.logger import get_logger
from app.context_writer import write_context
from app.podcast_state import PodcastState

logger = get_logger("podcast_renderer")

PODCAST_RENDERER_URL = "http://podcast_renderer:8009"


async def podcast_renderer_node(state: PodcastState) -> dict:
    episode_id = state["episode_id"]
    chapter_clips = state.get("chapter_clips") or []
    words = state.get("words") or []

    logger.info(f"[{episode_id[:8]}] Starting podcast_renderer — {len(chapter_clips)} chapters")

    rendered_chapters = []
    failed_chapters = []

    async with httpx.AsyncClient(timeout=36000) as client:
        # ── Step 1: render each chapter (card + captions) ──────────────────
        for clip in chapter_clips:
            try:
                response = await client.post(
                    f"{PODCAST_RENDERER_URL}/render_chapter",
                    json={
                        "episode_id": episode_id,
                        "clip_path": clip.get("file_path"),
                        "title": clip.get("title"),
                        "subtitle": clip.get("subtitle", ""),
                        "start_seconds": clip.get("start_seconds"),
                        "end_seconds": clip.get("end_seconds"),
                        "words": [w if isinstance(w, dict) else {"word": w.get("word",""), "start": w.get("start", 0.0), "end": w.get("end", 0.0)} for w in words],
                        "chapter_index": clip.get("chapter_index", 0),
                    },
                )
                response.raise_for_status()
                rendered_chapters.append(response.json())
                logger.info(
                    f"[{episode_id[:8]}] Chapter rendered: {clip.get('title')}"
                )
            except Exception as e:
                logger.error(
                    f"[{episode_id[:8]}] Render failed for '{clip.get('title')}': {e}"
                )
                failed_chapters.append({**clip, "error": str(e)})

        # ── Step 2: stitch all rendered chapters into one final MP4 ─────────
        final_video = None
        if rendered_chapters:
            chapter_paths = [c["rendered_path"] for c in rendered_chapters if c.get("rendered_path")]
            try:
                stitch_response = await client.post(
                    f"{PODCAST_RENDERER_URL}/stitch",
                    json={
                        "episode_id": episode_id,
                        "chapter_paths": chapter_paths,
                    },
                )
                stitch_response.raise_for_status()
                final_video = stitch_response.json().get("final_video")
                logger.info(f"[{episode_id[:8]}] Stitch done → {final_video}")
            except Exception as e:
                logger.error(f"[{episode_id[:8]}] Stitch failed: {e}")

    write_context(episode_id, "podcast_renderer", {
        "rendered_count": len(rendered_chapters),
        "failed_count": len(failed_chapters),
        "final_video": final_video,
    })

    return {
        "rendered_chapters": rendered_chapters,
        "failed_chapters": failed_chapters,
        "final_video": final_video,
        "pipeline_status": "completed",
    }