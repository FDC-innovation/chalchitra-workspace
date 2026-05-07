from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from app.core.database import get_session
from app.models.db import Episode
import httpx
import json
import os

router = APIRouter()

FFMPEG_URL = os.environ.get("FFMPEG_URL", "http://ffmpeg:8004")


@router.post("/{episode_id}")
async def render_episode(episode_id: str, session: Session = Depends(get_session)):
    """
    Render all generated clips for an episode.
    For each clip, calls the ffmpeg service to produce:
      - a landscape (16:9) file with intro, captions, and outro
      - a shorts (9:16) file with blur-pad and captions
    Saves results to episode.polished_clips.
    """
    episode = session.get(Episode, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    if not episode.generated_clips:
        raise HTTPException(status_code=400, detail="No clips generated yet — run /ffmpeg step first")
    if not episode.srt_file:
        raise HTTPException(status_code=400, detail="SRT file missing — run transcribe step first")
    if not os.path.exists(episode.srt_file):
        raise HTTPException(status_code=400, detail=f"SRT file not found on disk: {episode.srt_file}")

    clips = json.loads(episode.generated_clips)
    srt_content = open(episode.srt_file, encoding="utf-8").read()

    polished = []
    async with httpx.AsyncClient(timeout=600) as client:
        for i, clip in enumerate(clips):
            if clip.get("status") != "done":
                polished.append({**clip, "render_skipped": True})
                continue

            resp = await client.post(f"{FFMPEG_URL}/render", json={
                "episode_id": episode_id,
                "clip_path": clip["file_path"],
                "srt_content": srt_content,
                "start_seconds": clip.get("start_seconds", 0),
                "end_seconds": clip.get("end_seconds", 30),
                "clip_title": clip.get("title", f"Clip {i + 1}"),
                "show_title": episode.title or "Chalchitra",
                "clip_index": i,
            })

            if resp.status_code == 200:
                polished.append({**clip, **resp.json()})
            else:
                polished.append({**clip, "render_error": resp.text})

    episode.polished_clips = json.dumps(polished)
    session.add(episode)
    session.commit()

    return {"episode_id": episode_id, "polished_clips": polished}
