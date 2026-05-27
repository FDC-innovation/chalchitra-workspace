import httpx
import json
import logging
import os
import traceback
from sqlmodel import Session, select
from app.models.db import Episode, Job, JobStatus
from app.core.database import engine

logger = logging.getLogger("chalchitra.pipeline")

TRANSCRIPTION_URL = os.environ.get("TRANSCRIPTION_URL", "http://transcription:8001")
ENRICH_URL        = os.environ.get("ENRICH_URL",        "http://enrich:8002")
DETECT_URL        = os.environ.get("DETECT_URL",        "http://detect:8003")
FFMPEG_URL        = os.environ.get("FFMPEG_URL",        "http://ffmpeg:8004")


def _set_job(episode_id: str, step: str, status: JobStatus, message: str = "", error: str = None):
    """Open a fresh session, update the job, commit, close. Never shares state with caller."""
    with Session(engine) as s:
        job = s.exec(select(Job).where(Job.episode_id == episode_id, Job.step == step)).first()
        if job:
            job.status  = status
            job.message = message
            job.error   = error
            s.add(job)
            s.commit()


def _get_episode(episode_id: str) -> Episode:
    with Session(engine) as s:
        return s.get(Episode, episode_id)


def _save_episode(episode: Episode):
    """Merge episode into a fresh session and commit."""
    with Session(engine) as s:
        s.merge(episode)
        s.commit()


async def run_pipeline(episode_id: str, file_path: str):
    """Run the full pipeline: transcribe → enrich → detect → ffmpeg → render.
    Each step uses its own DB session so a crash never leaves a half-open transaction.
    """
    logger.info(f"[pipeline] starting for episode {episode_id}")

    episode = _get_episode(episode_id)
    if not episode:
        logger.error(f"[pipeline] episode {episode_id} not found")
        return

    # ── STEP 1: Transcribe ────────────────────────────────────────────────────
    _set_job(episode_id, "transcribe", JobStatus.processing, "Transcribing audio...")
    try:
        async with httpx.AsyncClient(timeout=600) as client:
            r = await client.post(f"{TRANSCRIPTION_URL}/transcribe", json={
                "episode_id": episode_id,
                "file_path":  file_path,
                "task":       "translate",
            })
            r.raise_for_status()
            data = r.json()

        episode.transcript   = data.get("text")
        episode.duration_sec = data.get("duration")
        episode.words_json   = json.dumps(data.get("words", []))
        episode.srt_file     = data.get("srt_path")
        _save_episode(episode)
        _set_job(episode_id, "transcribe", JobStatus.done, "Transcription complete")
        logger.info(f"[pipeline] transcribe done for {episode_id}")
    except Exception as e:
        _set_job(episode_id, "transcribe", JobStatus.failed, error=f"{type(e).__name__}: {e}")
        logger.error(f"[pipeline] transcribe failed: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        return

    # ── STEP 2: Enrich ────────────────────────────────────────────────────────
    _set_job(episode_id, "enrich", JobStatus.processing, "Generating metadata...")
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
        _save_episode(episode)
        _set_job(episode_id, "enrich", JobStatus.done, "Metadata generated")
        logger.info(f"[pipeline] enrich done for {episode_id}")
    except Exception as e:
        _set_job(episode_id, "enrich", JobStatus.failed, error=f"{type(e).__name__}: {e}")
        logger.error(f"[pipeline] enrich failed: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        return

    # ── STEP 3: Detect clips ──────────────────────────────────────────────────
    _set_job(episode_id, "detect", JobStatus.processing, "Detecting best clips...")
    try:
        srt_content = ""
        if episode.srt_file and os.path.exists(episode.srt_file):
            srt_content = open(episode.srt_file, encoding="utf-8").read()

        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{DETECT_URL}/detect", json={
                "episode_id": episode_id,
                "transcript": episode.transcript,
                "srt":        srt_content,
            })
            r.raise_for_status()
            data = r.json()

        episode.detected_clips = json.dumps(data.get("clips", []))
        _save_episode(episode)
        _set_job(episode_id, "detect", JobStatus.done, "Clips detected")
        logger.info(f"[pipeline] detect done for {episode_id}")
    except Exception as e:
        _set_job(episode_id, "detect", JobStatus.failed, error=f"{type(e).__name__}: {e}")
        logger.error(f"[pipeline] detect failed: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        return

    # ── STEP 4: Cut clips ────────────────────────────────────────────────────
    _set_job(episode_id, "ffmpeg", JobStatus.processing, "Cutting clips...")
    try:
        clips = json.loads(episode.detected_clips or "[]")
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(f"{FFMPEG_URL}/ffmpeg", json={
                "episode_id": episode_id,
                "file_path":  file_path,
                "clips":      clips,
            })
            r.raise_for_status()
            data = r.json()

        episode.generated_clips = json.dumps(data.get("clips", []))
        _save_episode(episode)
        _set_job(episode_id, "ffmpeg", JobStatus.done, "Clips cut")
        logger.info(f"[pipeline] ffmpeg done for {episode_id}")
    except Exception as e:
        _set_job(episode_id, "ffmpeg", JobStatus.failed, error=f"{type(e).__name__}: {e}")
        logger.error(f"[pipeline] ffmpeg failed: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        return

    # ── STEP 5: Render ────────────────────────────────────────────────────────
    _set_job(episode_id, "render", JobStatus.processing, "Rendering final clips...")
    try:
        clips       = json.loads(episode.generated_clips or "[]")
        srt_content = open(episode.srt_file, encoding="utf-8").read() if episode.srt_file else ""
        polished    = []

        for i, clip in enumerate(clips):
            if clip.get("status") != "done":
                polished.append({**clip, "render_skipped": True})
                continue

            # Skip if already rendered (crash-recovery: files exist from a previous attempt)
            lp = clip["file_path"].replace(".mp4", "") + f"_landscape.mp4"
            sp = clip["file_path"].replace(".mp4", "") + f"_shorts.mp4"
            base = os.path.join(os.path.dirname(clip["file_path"]), f"{episode_id}_clip{i}")
            lp = base + "_landscape.mp4"
            sp = base + "_shorts.mp4"
            if os.path.exists(lp) and os.path.exists(sp):
                logger.info(f"[pipeline] clip {i} already rendered, skipping ffmpeg call")
                polished.append({**clip, "landscape_path": lp, "shorts_path": sp, "clip_index": i})
                # Save progress so far in case we crash on a later clip
                episode.polished_clips = json.dumps(polished)
                _save_episode(episode)
                continue

            try:
                async with httpx.AsyncClient(timeout=900) as client:
                    r = await client.post(f"{FFMPEG_URL}/render", json={
                        "episode_id":    episode_id,
                        "clip_path":     clip["file_path"],
                        "srt_content":   srt_content,
                        "start_seconds": clip.get("start_seconds", 0),
                        "end_seconds":   clip.get("end_seconds", 30),
                        "clip_title":    clip.get("title") or f"Clip {i + 1}",
                        "show_title":    episode.title or "Chalchitra",
                        "clip_index":    i,
                        "words_json":    episode.words_json or "[]",
                    })
                if r.status_code == 200:
                    polished.append({**clip, **r.json()})
                else:
                    logger.error(f"[pipeline] clip {i} render returned {r.status_code}: {r.text[:200]}")
                    polished.append({**clip, "render_error": r.text})
            except Exception as clip_err:
                logger.error(f"[pipeline] clip {i} render exception: {type(clip_err).__name__}: {clip_err}\n{traceback.format_exc()}")
                polished.append({**clip, "render_error": f"{type(clip_err).__name__}: {clip_err}"})

            # Commit after every clip — crash on clip N+1 doesn't lose clips 0..N
            episode.polished_clips = json.dumps(polished)
            _save_episode(episode)

        episode.polished_clips = json.dumps(polished)
        episode.status = "done"
        _save_episode(episode)
        _set_job(episode_id, "render", JobStatus.done, "Render complete")
        logger.info(f"[pipeline] render done for {episode_id}")

    except Exception as e:
        _set_job(episode_id, "render", JobStatus.failed, error=f"{type(e).__name__}: {e}")
        logger.error(f"[pipeline] render failed: {type(e).__name__}: {e}\n{traceback.format_exc()}")
