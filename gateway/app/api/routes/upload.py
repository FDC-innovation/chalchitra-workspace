from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from sqlmodel import Session
from app.core.database import get_session, create_db
from app.models.db import Episode, Job
from app.core.config import settings
import shutil, uuid, os, httpx

router = APIRouter()

ALLOWED_EXTENSIONS = {".mp3", ".mp4", ".wav", ".m4a", ".ogg", ".webm", ".mkv", ".mov"}
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "http://n8n:5678/webhook-test/chalchitra")

@router.post("/")
async def upload_media(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    create_db()
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {ext}")

    episode_id = str(uuid.uuid4())
    filename   = f"{episode_id}{ext}"
    dest_path  = str(settings.UPLOAD_DIR / filename)

    with open(dest_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    episode = Episode(id=episode_id, original_file=dest_path)
    session.add(episode)

    for step in ["transcribe", "enrich", "detect", "ffmpeg"]:
        job = Job(episode_id=episode_id, step=step)
        session.add(job)

    session.commit()

    background_tasks.add_task(trigger_n8n, episode_id, dest_path)

    return {
        "episode_id": episode_id,
        "message": "Upload received. Pipeline started.",
        "file": filename,
    }

async def trigger_n8n(episode_id: str, file_path: str):
    try:
        async with httpx.AsyncClient(timeout=600) as client:
            r = await client.post(N8N_WEBHOOK_URL, json={
                "episode_id": episode_id,
                "file_path": file_path,
            })
            r.raise_for_status()
    except Exception as e:
        print(f"[upload] n8n trigger failed: {e}")