from contextlib import asynccontextmanager
from typing import List, Optional
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.graph import build_graph
from app.podcast_graph import build_podcast_graph


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncSqliteSaver.from_conn_string("checkpoints_clips.db") as clip_checkpointer:
        async with AsyncSqliteSaver.from_conn_string("checkpoints_podcast.db") as podcast_checkpointer:
            app.state.graph = build_graph(clip_checkpointer)
            app.state.podcast_graph = build_podcast_graph(podcast_checkpointer)
            yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Default prompts exposed to UI ────────────────────────────────────────────

DEFAULT_ENRICH_PROMPT = """Given this transcript, extract metadata to help create viral short-form clips.

Transcript:
{transcript}

Return ONLY valid JSON:
{{
  "title": "catchy overall title for the content",
  "show_notes": "2-3 sentence summary",
  "tags": ["tag1", "tag2", "tag3"],
  "chapters": [{{"title": "chapter title", "start_time": "0:00", "summary": "brief summary"}}]
}}"""

DEFAULT_DETECT_PROMPT = """Analyze this transcript and find the best clips.

Transcript:
{transcript}

Rules:
- Each clip must be 20-90 seconds long
- Pick 2-4 clips maximum
- Clips must not overlap

Return ONLY valid JSON:
{{
  "clips": [
    {{
      "title": "punchy title max 6 words",
      "start_seconds": 0,
      "end_seconds": 45,
      "reason": "why this works as a clip"
    }}
  ]
}}"""

DEFAULT_CHAPTERS_PROMPT = """You are a podcast editor. Given the transcript below, identify 4-8 major chapters covering distinct topics.
For each chapter return:
- title: short punchy chapter title (max 6 words)
- subtitle: one sentence describing what this chapter covers
- start_seconds: float
- end_seconds: float

Return ONLY a raw JSON array. No markdown, no backticks, no explanation."""


# ── Request models ───────────────────────────────────────────────────────────

class StartRequest(BaseModel):
    episode_id: Optional[str] = None
    file_path: str
    transcription_engine: Optional[str] = "whisper"


class ApproveTranscriptRequest(BaseModel):
    episode_id: str
    transcript_text: Optional[str] = None  # edited transcript


class ApprovePromptRequest(BaseModel):
    episode_id: str
    prompt: Optional[str] = None           # edited prompt (or None = use default)
    prompt_type: str                        # "enrich" | "detect" | "chapters"


class ApproveClipsRequest(BaseModel):
    episode_id: str
    approved_clips: List[dict]
    human_feedback: Optional[str] = None


class RejectRequest(BaseModel):
    episode_id: str
    feedback: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _clips_config(episode_id: str) -> dict:
    return {"configurable": {"thread_id": episode_id}}


def _podcast_config(episode_id: str) -> dict:
    return {"configurable": {"thread_id": f"podcast:{episode_id}"}}


async def _resume(graph, config):
    import asyncio
    async def _run():
        await graph.ainvoke(None, config=config)
    return _run


# ── Default prompts endpoint ─────────────────────────────────────────────────

@app.get("/pipeline/defaults")
def get_defaults():
    return {
        "enrich_prompt": DEFAULT_ENRICH_PROMPT,
        "detect_prompt": DEFAULT_DETECT_PROMPT,
    }


@app.get("/podcast/defaults")
def get_podcast_defaults():
    return {
        "chapters_prompt": DEFAULT_CHAPTERS_PROMPT,
    }


# ── CLIPS PIPELINE ───────────────────────────────────────────────────────────

@app.post("/pipeline/start")
async def start_pipeline(request: StartRequest):
    episode_id = request.episode_id or str(uuid.uuid4())
    config = _clips_config(episode_id)
    await app.state.graph.ainvoke(
        {
            "episode_id": episode_id,
            "file_path": request.file_path,
            "transcription_engine": request.transcription_engine,
        },
        config=config,
    )
    return {"episode_id": episode_id}


@app.get("/pipeline/status/{episode_id}")
async def get_status(episode_id: str):
    config = _clips_config(episode_id)
    snapshot = await app.state.graph.aget_state(config)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    next_nodes = list(snapshot.next)
    return {
        "episode_id": episode_id,
        "state": snapshot.values,
        "next": next_nodes,
        "at_interrupt": len(next_nodes) > 0,
        "interrupt_type": next_nodes[0] if next_nodes else None,
    }


@app.post("/pipeline/approve/transcript")
async def approve_transcript(request: ApproveTranscriptRequest, background_tasks: BackgroundTasks):
    config = _clips_config(request.episode_id)
    snapshot = await app.state.graph.aget_state(config)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    if not snapshot.next or snapshot.next[0] != "transcript_review":
        raise HTTPException(status_code=400, detail="Pipeline is not at transcript review.")

    updates = {}
    if request.transcript_text is not None:
        updates["transcript_text"] = request.transcript_text
    await app.state.graph.aupdate_state(config, updates, as_node="transcript_review")

    async def _run():
        await app.state.graph.ainvoke(None, config=config)
    background_tasks.add_task(_run)
    return {"status": "resumed", "next": "prompt_review_enrich"}


@app.post("/pipeline/approve/prompt")
async def approve_prompt(request: ApprovePromptRequest, background_tasks: BackgroundTasks):
    config = _clips_config(request.episode_id)
    snapshot = await app.state.graph.aget_state(config)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    next_node = snapshot.next[0] if snapshot.next else None

    if request.prompt_type == "enrich":
        if next_node != "prompt_review_enrich":
            raise HTTPException(status_code=400, detail="Not at enrich prompt review.")
        updates = {"enrich_prompt": request.prompt or DEFAULT_ENRICH_PROMPT}
        await app.state.graph.aupdate_state(config, updates, as_node="prompt_review_enrich")
    elif request.prompt_type == "detect":
        if next_node != "prompt_review_detect":
            raise HTTPException(status_code=400, detail="Not at detect prompt review.")
        updates = {"detect_prompt": request.prompt or DEFAULT_DETECT_PROMPT}
        await app.state.graph.aupdate_state(config, updates, as_node="prompt_review_detect")
    else:
        raise HTTPException(status_code=400, detail="Unknown prompt_type")

    async def _run():
        await app.state.graph.ainvoke(None, config=config)
    background_tasks.add_task(_run)
    return {"status": "resumed"}


@app.post("/pipeline/reject")
async def reject_pipeline(request: RejectRequest):
    config = _clips_config(request.episode_id)
    await app.state.graph.aupdate_state(config, {
        "pipeline_status": "rejected",
        "human_feedback": request.feedback,
    })
    return {"episode_id": request.episode_id, "status": "rejected"}


# ── PODCAST PIPELINE ─────────────────────────────────────────────────────────

@app.post("/podcast/start")
async def start_podcast(request: StartRequest):
    episode_id = request.episode_id or str(uuid.uuid4())
    config = _podcast_config(episode_id)
    await app.state.podcast_graph.ainvoke(
        {
            "episode_id": episode_id,
            "file_path": request.file_path,
            "transcription_engine": request.transcription_engine,
        },
        config=config,
    )
    return {"episode_id": episode_id}


@app.get("/podcast/status/{episode_id}")
async def get_podcast_status(episode_id: str):
    config = _podcast_config(episode_id)
    snapshot = await app.state.podcast_graph.aget_state(config)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Podcast pipeline not found")
    next_nodes = list(snapshot.next)
    return {
        "episode_id": episode_id,
        "state": snapshot.values,
        "next": next_nodes,
        "at_interrupt": len(next_nodes) > 0,
        "interrupt_type": next_nodes[0] if next_nodes else None,
    }


@app.post("/podcast/approve/transcript")
async def approve_podcast_transcript(request: ApproveTranscriptRequest, background_tasks: BackgroundTasks):
    config = _podcast_config(request.episode_id)
    snapshot = await app.state.podcast_graph.aget_state(config)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Podcast pipeline not found")
    if not snapshot.next or snapshot.next[0] != "transcript_review":
        raise HTTPException(status_code=400, detail="Not at transcript review.")

    updates = {}
    if request.transcript_text is not None:
        updates["transcript_text"] = request.transcript_text
    await app.state.podcast_graph.aupdate_state(config, updates, as_node="transcript_review")

    async def _run():
        await app.state.podcast_graph.ainvoke(None, config=config)
    background_tasks.add_task(_run)
    return {"status": "resumed", "next": "prompt_review_chapters"}


@app.post("/podcast/approve/prompt")
async def approve_podcast_prompt(request: ApprovePromptRequest, background_tasks: BackgroundTasks):
    config = _podcast_config(request.episode_id)
    snapshot = await app.state.podcast_graph.aget_state(config)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Podcast pipeline not found")

    next_node = snapshot.next[0] if snapshot.next else None
    if next_node != "prompt_review_chapters":
        raise HTTPException(status_code=400, detail="Not at chapters prompt review.")

    updates = {"chapters_prompt": request.prompt or DEFAULT_CHAPTERS_PROMPT}
    await app.state.podcast_graph.aupdate_state(config, updates, as_node="prompt_review_chapters")

    async def _run():
        await app.state.podcast_graph.ainvoke(None, config=config)
    background_tasks.add_task(_run)
    return {"status": "resumed"}


@app.post("/podcast/reject")
async def reject_podcast(request: RejectRequest):
    config = _podcast_config(request.episode_id)
    await app.state.podcast_graph.aupdate_state(config, {
        "pipeline_status": "rejected",
        "human_feedback": request.feedback,
    })
    return {"episode_id": request.episode_id, "status": "rejected"}