from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from sqlmodel import Session
from app.core.database import get_session, create_db
from app.core.config import settings
from app.models.db import Episode, Job
import shutil, uuid, os, httpx, logging

logger = logging.getLogger("chalchitra")
router = APIRouter()

ALLOWED_EXTENSIONS = {".mp3", ".mp4", ".wav", ".m4a", ".ogg", ".webm", ".mkv", ".mov"}
ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://orchestrator:8007/pipeline/start")


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
    filename = f"{episode_id}{ext}"
    dest_path = str(settings.UPLOAD_DIR / filename)

    with open(dest_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    episode = Episode(id=episode_id, original_file=dest_path)
    session.add(episode)

    for step in ["transcribe", "enrich", "detect", "ffmpeg", "render"]:
        session.add(Job(episode_id=episode_id, step=step))

    session.commit()

    logger.info(f"[upload] episode={episode_id} → triggering orchestrator at {ORCHESTRATOR_URL}")
    background_tasks.add_task(trigger_pipeline, episode_id, dest_path)

    return {
        "episode_id": episode_id,
        "message": "Upload received. Pipeline started.",
        "file": filename,
    }


async def trigger_pipeline(episode_id: str, file_path: str):
    payload = {"episode_id": episode_id, "file_path": file_path, "transcription_engine": "whisper"}
    logger.info(f"[orchestrator] POST {ORCHESTRATOR_URL} payload={payload}")
    try:
        async with httpx.AsyncClient(timeout=600) as client:
            r = await client.post(ORCHESTRATOR_URL, json=payload)
            r.raise_for_status()
            logger.info(f"[orchestrator] {r.status_code}: {r.text[:300]}")
    except httpx.HTTPStatusError as e:
        logger.error(f"[orchestrator] HTTP {e.response.status_code}: {e.response.text[:300]}")
    except Exception as e:
        logger.error(f"[orchestrator] failed: {e}")
