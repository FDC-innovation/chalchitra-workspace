from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from app.core.database import get_session
from app.models.db import Job

router = APIRouter()


@router.get("/")
def list_jobs(session: Session = Depends(get_session)):
    jobs = session.exec(select(Job).order_by(Job.created_at.desc())).all()
    return jobs
