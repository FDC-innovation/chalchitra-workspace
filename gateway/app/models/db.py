from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
import uuid


class Episode(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    original_file: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = "pending"


class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    episode_id: str = Field(foreign_key="episode.id")
    step: str
    status: str = "pending"
    created_at: datetime = Field(default_factory=datetime.utcnow)
