import httpx
import json
import logging
import os
from sqlmodel import Session
from app.models.db import Episode, Job, JobStatus
from app.core.database import engine
from sqlmodel import select

logger = logging.getLogger("chalchitra.pipeline")

TRANSCRIPTION_URL = os.environ.get("TRANSCRIPTION_URL", "http://transcription:8001")
ENRICH_URL        = os.environ.get("ENRICH_URL",        "http://enrich:8002")
DETECT_URL        = os.environ.get("DETECT_URL",        "http://detect:8003")
FFMPEG_URL        = os.environ.get("FFMPEG_URL",        "http://ffmpeg:8004")


def _get_job(session: Session, episode_id: str, step: str) -> Job:
    return session.exec(
        select(Job).where(Job.episode_id == episode_id, Job.step == step)
    ).first()


def _set_job(session: Session, episode_id: str, step: str, status: JobStatus, message: str = "", error: str = None):
    job = _get_job(session, episode_id, step)
    if job:
        job.status = status
        job.message = message
        job.error = error
        session.add(job)
        session.commit()


async def run_pipeline(episode_id: str, file_path: str):
    """Run the full pipeline for an episode: transcribe → enrich → detect → ffmpeg → render."""
    logger.info(f"[pipeline] starting for episode {episode_id}")

    with Session(engine) as session:
        episode = session.get(Episode, episode_id)
        if not episode:
            logger.error(f"[pipeline] episode {episode_id} not found")
            return

        # ── STEP 1: Transcribe ────────────────────────────────────────────
        _set_job(session, episode_id, "transcribe", JobStatus.processing, "Transcribing audio...")
        try:
            async with httpx.AsyncClient(timeout=600) as client:
                r = await client.post(f"{TRANSCRIPTION_URL}/transcribe", json={
                    "episode_id": episode_id,
                    "file_path": file_path,
                    "task": "translate",   # always output English regardless of source language
                })
                r.raise_for_status()
                data = r.json()

            episode.transcript    = data.get("text")
            episode.duration_sec  = data.get("duration")
            episode.words_json    = json.dumps(data.get("words", []))
            episode.srt_file      = data.get("srt_path")
            session.add(episode)
            session.commit()
            _set_job(session, episode_id, "transcribe", JobStatus.done, "Transcription complete")
            logger.info(f"[pipeline] transcribe done for {episode_id}")
        except Exception as e:
            _set_job(session, episode_id, "transcribe", JobStatus.failed, error=str(e))
            logger.error(f"[pipeline] transcribe failed: {e}")
            return

        # ── STEP 2: Enrich ────────────────────────────────────────────────
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
            logger.info(f"[pipeline] enrich done for {episode_id}")
        except Exception as e:
            _set_job(session, episode_id, "enrich", JobStatus.failed, error=str(e))
            logger.error(f"[pipeline] enrich failed: {e}")
            return

        # ── STEP 3: Detect clips ──────────────────────────────────────────
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
            logger.info(f"[pipeline] detect done for {episode_id}")
        except Exception as e:
            _set_job(session, episode_id, "detect", JobStatus.failed, error=str(e))
            logger.error(f"[pipeline] detect failed: {e}")
            return

        # ── STEP 4: Cut clips with FFmpeg ─────────────────────────────────
        _set_job(session, episode_id, "ffmpeg", JobStatus.processing, "Cutting clips...")
        try:
            clips = json.loads(episode.detected_clips or "[]")
            async with httpx.AsyncClient(timeout=300) as client:
                r = await client.post(f"{FFMPEG_URL}/ffmpeg", json={
                    "episode_id": episode_id,
                    "file_path": file_path,
                    "clips": clips,
                })
                r.raise_for_status()
                data = r.json()

            episode.generated_clips = json.dumps(data.get("clips", []))
            session.add(episode)
            session.commit()
            _set_job(session, episode_id, "ffmpeg", JobStatus.done, "Clips cut")
            logger.info(f"[pipeline] ffmpeg done for {episode_id}")
        except Exception as e:
            _set_job(session, episode_id, "ffmpeg", JobStatus.failed, error=str(e))
            logger.error(f"[pipeline] ffmpeg failed: {e}")
            return

        # ── STEP 5: Render (captions + intro + shorts) ────────────────────
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
            logger.info(f"[pipeline] render done for {episode_id}")
        except Exception as e:
            _set_job(session, episode_id, "render", JobStatus.failed, error=str(e))
            logger.error(f"[pipeline] render failed: {e}")
