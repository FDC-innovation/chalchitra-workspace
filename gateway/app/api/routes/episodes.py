from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from app.core.database import get_session
from app.models.db import Episode, Job

router = APIRouter()


@router.get("/")
def list_episodes(session: Session = Depends(get_session)):
    episodes = session.exec(select(Episode).order_by(Episode.created_at.desc())).all()
    return episodes


@router.get("/{episode_id}")
def get_episode(episode_id: str, session: Session = Depends(get_session)):
    episode = session.get(Episode, episode_id)
    if not episode:
        raise HTTPException(404, "Episode not found")
    jobs = session.exec(select(Job).where(Job.episode_id == episode_id)).all()
    return {"episode": episode, "jobs": jobs}
