from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlmodel import Session
from app.core.database import get_session
from app.models.db import Episode
from app.services.pipeline import run_pipeline

router = APIRouter()


@router.post("/api/steps/run/{episode_id}")
async def run_episode_pipeline(
    episode_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """Manually trigger the full pipeline for an existing episode."""
    episode = session.get(Episode, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    background_tasks.add_task(run_pipeline, episode_id, episode.original_file)
    return {"episode_id": episode_id, "message": "Pipeline triggered"}
