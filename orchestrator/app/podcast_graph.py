from typing import Optional
from typing_extensions import TypedDict

import httpx
from langgraph.graph import StateGraph, END


class PodcastState(TypedDict):
    episode_id: str
    file_path: str
    pipeline_status: Optional[str]
    silence_segments: Optional[list]
    edit_decisions: Optional[list]
    edited_file: Optional[str]
    transcript_text: Optional[str]
    srt: Optional[str]
    words: Optional[list]
    title: Optional[str]
    show_notes: Optional[str]
    tags: Optional[list]
    chapters: Optional[list]
    approved_chapters: Optional[list]
    final_episode_path: Optional[str]
    detected_clips: Optional[list]
    approved_clips: Optional[list]
    rendered_clips: Optional[list]
    failed_clips: Optional[list]
    human_feedback: Optional[str]
    summary: Optional[dict]
    error: Optional[str]


async def _detect_silence(state: PodcastState) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "http://silence_detector:8008/detect_silence",
            json={"episode_id": state["episode_id"], "file_path": state["file_path"]},
            timeout=300,
        )
        r.raise_for_status()
        data = r.json()
    return {
        "silence_segments": data.get("segments", []),
        "pipeline_status": "awaiting_edit_approval",
    }


async def _auto_edit(state: PodcastState) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "http://auto_editor:8010/edit",
            json={
                "episode_id": state["episode_id"],
                "file_path": state["file_path"],
                "segments": state.get("silence_segments", []),
            },
            timeout=600,
        )
        r.raise_for_status()
        data = r.json()
    return {
        "edit_decisions": data.get("edl", []),
        "edited_file": data.get("output_file"),
        "pipeline_status": "edited",
    }


async def _transcribe(state: PodcastState) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "http://transcription:8001/transcribe",
            json={"episode_id": state["episode_id"], "file_path": state["edited_file"]},
            timeout=None,
        )
        r.raise_for_status()
        data = r.json()
    return {
        "transcript_text": data.get("transcript_text"),
        "srt": data.get("srt"),
        "words": data.get("words"),
    }


async def _enrich(state: PodcastState) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "http://enrich:8002/enrich",
            json={"episode_id": state["episode_id"], "transcript": state["transcript_text"]},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
    return {
        "title": data.get("title"),
        "show_notes": data.get("show_notes"),
        "tags": data.get("tags"),
        "chapters": data.get("chapters"),
    }


async def _structure(state: PodcastState) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "http://detect:8003/detect",
            json={
                "episode_id": state["episode_id"],
                "transcript": state["transcript_text"],
                "srt": state["srt"],
            },
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
    return {
        "chapters": data.get("clips", []),
        "pipeline_status": "awaiting_chapter_approval",
    }


async def _detect_clips(state: PodcastState) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "http://detect:8003/detect",
            json={
                "episode_id": state["episode_id"],
                "transcript": state["transcript_text"],
                "srt": state["srt"],
            },
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
    return {
        "detected_clips": data.get("clips", []),
        "pipeline_status": "awaiting_clip_approval",
    }


async def _renderer(state: PodcastState) -> dict:
    approved_clips = state.get("approved_clips") or []
    rendered_clips = []
    failed_clips = []

    async with httpx.AsyncClient() as client:
        for clip in approved_clips:
            try:
                r = await client.post(
                    "http://renderer:8006/render",
                    json={
                        "episode_id": state["episode_id"],
                        "clip_path": clip.get("clip_path"),
                        "title": clip.get("title"),
                        "start_seconds": clip.get("start_seconds"),
                        "end_seconds": clip.get("end_seconds"),
                        "words": state.get("words"),
                        "channel_name": "Chalchitra",
                        "cta_text": "Follow for more",
                    },
                    timeout=600,
                )
                r.raise_for_status()
                rendered_clips.append(r.json())
            except Exception as e:
                failed_clips.append({**clip, "error": str(e)})

    return {
        "rendered_clips": rendered_clips,
        "failed_clips": failed_clips,
        "pipeline_status": "completed",
    }


def build_podcast_graph(checkpointer):
    builder = StateGraph(PodcastState)

    builder.add_node("detect_silence", _detect_silence)
    builder.add_node("auto_edit", _auto_edit)
    builder.add_node("transcribe", _transcribe)
    builder.add_node("enrich", _enrich)
    builder.add_node("structure", _structure)
    builder.add_node("detect_clips", _detect_clips)
    builder.add_node("renderer", _renderer)

    builder.set_entry_point("detect_silence")
    builder.add_edge("detect_silence", "auto_edit")
    builder.add_edge("auto_edit", "transcribe")
    builder.add_edge("transcribe", "enrich")
    builder.add_edge("enrich", "structure")
    builder.add_edge("structure", "detect_clips")
    builder.add_edge("detect_clips", "renderer")
    builder.add_edge("renderer", END)

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["auto_edit", "detect_clips", "renderer"],
    )
