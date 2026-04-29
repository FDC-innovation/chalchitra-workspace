from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum

class JobStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"

class Episode(SQLModel, table=True):
    id: str = Field(primary_key=True)
    original_file: str
    status: str = "pending"
    transcript: Optional[str] = None
    duration_sec: Optional[float] = None
    words_json: Optional[str] = None
    srt_file: Optional[str] = None
    speaker_segments: Optional[str] = None
    title: Optional[str] = None
    show_notes: Optional[str] = None
    tags: Optional[str] = None
    chapters: Optional[str] = None
    detected_clips: Optional[str] = None
    generated_clips: Optional[str] = None
    polished_clips: Optional[str] = None
    audio_file: Optional[str] = None
    thumbnail: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    episode_id: str
    step: str
    status: JobStatus = JobStatus.pending
    progress: int = 0
    message: str = ""
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)