from contextlib import asynccontextmanager
from typing import List, Optional
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.graph import build_graph
from app.podcast_graph import build_podcast_graph


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as checkpointer:
        app.state.graph = build_graph(checkpointer)
        app.state.podcast_graph = build_podcast_graph(checkpointer)
        yield


app = FastAPI(lifespan=lifespan)


class StartRequest(BaseModel):
    episode_id: Optional[str] = None
    file_path: str


class ApproveRequest(BaseModel):
    episode_id: str
    approved_clips: List[dict]


class RejectRequest(BaseModel):
    episode_id: str
    feedback: Optional[str] = None


@app.post("/pipeline/start")
async def start_pipeline(request: StartRequest):
    episode_id = request.episode_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": episode_id}}

    state = await app.state.graph.ainvoke(
        {"episode_id": episode_id, "file_path": request.file_path},
        config=config,
    )

    return {"episode_id": episode_id, "state": state}


@app.get("/pipeline/status/{episode_id}")
async def get_status(episode_id: str):
    config = {"configurable": {"thread_id": episode_id}}
    snapshot = await app.state.graph.aget_state(config)

    if snapshot is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    return {"episode_id": episode_id, "state": snapshot.values}


@app.post("/pipeline/approve")
async def approve_pipeline(request: ApproveRequest):
    config = {"configurable": {"thread_id": request.episode_id}}

    await app.state.graph.aupdate_state(
        config,
        {"approved_clips": request.approved_clips},
    )

    state = await app.state.graph.ainvoke(None, config=config)

    return {"episode_id": request.episode_id, "state": state}


@app.post("/pipeline/reject")
async def reject_pipeline(request: RejectRequest):
    config = {"configurable": {"thread_id": request.episode_id}}

    await app.state.graph.aupdate_state(
        config,
        {
            "pipeline_status": "rejected",
            "human_feedback": request.feedback,
        },
    )

    return {"episode_id": request.episode_id, "status": "rejected"}


# ---------------------------------------------------------------------------
# Podcast pipeline
# ---------------------------------------------------------------------------

class PodcastApproveRequest(BaseModel):
    episode_id: str
    updates: dict  # flexible: approved_chapters, approved_clips, or any state patch


def _podcast_config(episode_id: str) -> dict:
    return {"configurable": {"thread_id": f"podcast:{episode_id}"}}


@app.post("/podcast/start")
async def start_podcast(request: StartRequest):
    episode_id = request.episode_id or str(uuid.uuid4())
    config = _podcast_config(episode_id)

    state = await app.state.podcast_graph.ainvoke(
        {"episode_id": episode_id, "file_path": request.file_path},
        config=config,
    )

    return {"episode_id": episode_id, "state": state}


@app.get("/podcast/status/{episode_id}")
async def get_podcast_status(episode_id: str):
    config = _podcast_config(episode_id)
    snapshot = await app.state.podcast_graph.aget_state(config)

    if snapshot is None:
        raise HTTPException(status_code=404, detail="Podcast pipeline not found")

    return {"episode_id": episode_id, "state": snapshot.values}


@app.post("/podcast/approve")
async def approve_podcast(request: PodcastApproveRequest):
    config = _podcast_config(request.episode_id)

    await app.state.podcast_graph.aupdate_state(config, request.updates)
    state = await app.state.podcast_graph.ainvoke(None, config=config)

    return {"episode_id": request.episode_id, "state": state}
