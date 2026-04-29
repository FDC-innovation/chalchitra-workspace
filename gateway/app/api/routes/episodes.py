from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from app.core.database import get_session
from app.models.db import Episode

router = APIRouter()

@router.get("/")
def list_episodes(session: Session = Depends(get_session)):
    return session.exec(select(Episode)).all()

@router.get("/{episode_id}")
def get_episode(episode_id: str, session: Session = Depends(get_session)):
    ep = session.get(Episode, episode_id)
    return ep