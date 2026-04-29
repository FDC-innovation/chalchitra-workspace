from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from app.core.database import get_session
from app.models.db import Job

router = APIRouter()

@router.get("/{episode_id}")
def get_jobs(episode_id: str, session: Session = Depends(get_session)):
    return session.exec(select(Job).where(Job.episode_id == episode_id)).all()