from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlmodel import Session, select
from app.core.database import get_session
from app.models.db import Episode, Job, JobStatus
from app.services.pipeline import run_pipeline
from app.core.config import settings
import httpx
import json
import os

router = APIRouter()

TRANSCRIPTION_URL = os.environ.get("TRANSCRIPTION_URL", "http://transcription:8001")
ENRICH_URL        = os.environ.get("ENRICH_URL",        "http://enrich:8002")
DETECT_URL        = os.environ.get("DETECT_URL",        "http://detect:8003")
FFMPEG_URL        = os.environ.get("FFMPEG_URL",        "http://ffmpeg:8004")


def _set_job(session: Session, episode_id: str, step: str, status: JobStatus, message: str = "", error: str = None):
    job = session.exec(select(Job).where(Job.episode_id == episode_id, Job.step == step)).first()
    if job:
        job.status  = status
        job.message = message
        job.error   = error
        session.add(job)
        session.commit()


# ── Manual full pipeline trigger ──────────────────────────────────────────────

@router.post("/api/steps/run/{episode_id}")
async def run_episode_pipeline(
    episode_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """Manually trigger the full pipeline for an existing episode (fallback, no n8n)."""
    episode = session.get(Episode, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    background_tasks.add_task(run_pipeline, episode_id, episode.original_file)
    return {"episode_id": episode_id, "message": "Pipeline triggered"}


# ── Individual step endpoints (called by n8n nodes) ───────────────────────────

@router.post("/api/steps/transcribe/{episode_id}")
async def step_transcribe(episode_id: str, session: Session = Depends(get_session)):
    """n8n Step 1 — Transcribe audio to English text with word timestamps."""
    episode = session.get(Episode, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    _set_job(session, episode_id, "transcribe", JobStatus.processing, "Transcribing audio...")
    try:
        async with httpx.AsyncClient(timeout=600) as client:
            r = await client.post(f"{TRANSCRIPTION_URL}/transcribe", json={
                "episode_id": episode_id,
                "file_path": episode.original_file,
                "task": "translate",
            })
            r.raise_for_status()
            data = r.json()

        episode.transcript   = data.get("text")
        episode.duration_sec = data.get("duration")
        episode.words_json   = json.dumps(data.get("words", []))
        episode.srt_file     = data.get("srt_path")
        session.add(episode)
        session.commit()
        _set_job(session, episode_id, "transcribe", JobStatus.done, "Transcription complete")
        return {"episode_id": episode_id, "status": "done", "step": "transcribe"}
    except Exception as e:
        _set_job(session, episode_id, "transcribe", JobStatus.failed, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/steps/enrich/{episode_id}")
async def step_enrich(episode_id: str, session: Session = Depends(get_session)):
    """n8n Step 2 — Generate title, show notes, tags and chapters using Claude."""
    episode = session.get(Episode, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    _set_job(session, episode_id, "enrich", JobStatus.processing, "Generating metadata...")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{ENRICH_URL}/enrich", json={
                "episode_id": episode_id,
                "transcript": episode.transcript,
            })
            r.raise_for_status()
            data = r.json()

        episode.title      = data.get("title")
        episode.show_notes = data.get("show_notes")
        episode.tags       = json.dumps(data.get("tags", []))
        episode.chapters   = json.dumps(data.get("chapters", []))
        session.add(episode)
        session.commit()
        _set_job(session, episode_id, "enrich", JobStatus.done, "Metadata generated")
        return {"episode_id": episode_id, "status": "done", "step": "enrich"}
    except Exception as e:
        _set_job(session, episode_id, "enrich", JobStatus.failed, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/steps/detect/{episode_id}")
async def step_detect(episode_id: str, session: Session = Depends(get_session)):
    """n8n Step 3 — Detect the 3 best viral clip segments using Claude."""
    episode = session.get(Episode, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    _set_job(session, episode_id, "detect", JobStatus.processing, "Detecting best clips...")
    try:
        srt_content = ""
        if episode.srt_file and os.path.exists(episode.srt_file):
            srt_content = open(episode.srt_file, encoding="utf-8").read()

        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{DETECT_URL}/detect", json={
                "episode_id": episode_id,
                "transcript": episode.transcript,
                "srt": srt_content,
            })
            r.raise_for_status()
            data = r.json()

        episode.detected_clips = json.dumps(data.get("clips", []))
        session.add(episode)
        session.commit()
        _set_job(session, episode_id, "detect", JobStatus.done, "Clips detected")
        return {"episode_id": episode_id, "status": "done", "step": "detect"}
    except Exception as e:
        _set_job(session, episode_id, "detect", JobStatus.failed, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/steps/ffmpeg/{episode_id}")
async def step_ffmpeg(episode_id: str, session: Session = Depends(get_session)):
    """n8n Step 4 — Cut detected clips from the source video using FFmpeg."""
    episode = session.get(Episode, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    _set_job(session, episode_id, "ffmpeg", JobStatus.processing, "Cutting clips...")
    try:
        clips = json.loads(episode.detected_clips or "[]")
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(f"{FFMPEG_URL}/ffmpeg", json={
                "episode_id": episode_id,
                "file_path": episode.original_file,
                "clips": clips,
            })
            r.raise_for_status()
            data = r.json()

        episode.generated_clips = json.dumps(data.get("clips", []))
        session.add(episode)
        session.commit()
        _set_job(session, episode_id, "ffmpeg", JobStatus.done, "Clips cut")
        return {"episode_id": episode_id, "status": "done", "step": "ffmpeg"}
    except Exception as e:
        _set_job(session, episode_id, "ffmpeg", JobStatus.failed, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/steps/render/{episode_id}")
async def step_render(episode_id: str, session: Session = Depends(get_session)):
    """n8n Step 5 — Render animated captions, blurred intro/outro for each clip."""
    episode = session.get(Episode, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    _set_job(session, episode_id, "render", JobStatus.processing, "Rendering final clips...")
    try:
        clips = json.loads(episode.generated_clips or "[]")
        srt_content = open(episode.srt_file, encoding="utf-8").read() if episode.srt_file else ""

        polished = []
        async with httpx.AsyncClient(timeout=600) as client:
            for i, clip in enumerate(clips):
                if clip.get("status") != "done":
                    polished.append({**clip, "render_skipped": True})
                    continue
                r = await client.post(f"{FFMPEG_URL}/render", json={
                    "episode_id": episode_id,
                    "clip_path": clip["file_path"],
                    "srt_content": srt_content,
                    "start_seconds": clip.get("start_seconds", 0),
                    "end_seconds": clip.get("end_seconds", 30),
                    "clip_title": clip.get("title", f"Clip {i + 1}"),
                    "show_title": episode.title or "Chalchitra",
                    "clip_index": i,
                    "words_json": episode.words_json or "[]",
                })
                if r.status_code == 200:
                    polished.append({**clip, **r.json()})
                else:
                    polished.append({**clip, "render_error": r.text})

        episode.polished_clips = json.dumps(polished)
        episode.status = "done"
        session.add(episode)
        session.commit()
        _set_job(session, episode_id, "render", JobStatus.done, "Render complete")
        return {"episode_id": episode_id, "status": "done", "step": "render"}
    except Exception as e:
        _set_job(session, episode_id, "render", JobStatus.failed, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
