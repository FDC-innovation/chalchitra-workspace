from langgraph.graph import StateGraph, END
from app.state import ChalchitraState
from app.nodes.transcribe import transcribe_node
from app.nodes.enrich import enrich_node
from app.nodes.detect import detect_node
from app.nodes.ffmpeg import ffmpeg_node
from app.nodes.filter_clips import filter_clips_node
from app.nodes.renderer import renderer_node


async def transcript_review_node(state: ChalchitraState) -> dict:
    """No-op node — just a pause point for human transcript review."""
    return {}


async def prompt_review_enrich_node(state: ChalchitraState) -> dict:
    """No-op node — pause point for human to edit enrich prompt."""
    return {}


async def prompt_review_detect_node(state: ChalchitraState) -> dict:
    """No-op node — pause point for human to edit detect prompt."""
    return {}


def build_graph(checkpointer):
    builder = StateGraph(ChalchitraState)

    builder.add_node("transcribe", transcribe_node)
    builder.add_node("transcript_review", transcript_review_node)
    builder.add_node("prompt_review_enrich", prompt_review_enrich_node)
    builder.add_node("enrich", enrich_node)
    builder.add_node("prompt_review_detect", prompt_review_detect_node)
    builder.add_node("detect", detect_node)
    builder.add_node("ffmpeg", ffmpeg_node)
    builder.add_node("filter_clips", filter_clips_node)
    builder.add_node("renderer", renderer_node)

    builder.set_entry_point("transcribe")
    builder.add_edge("transcribe", "transcript_review")
    builder.add_edge("transcript_review", "prompt_review_enrich")
    builder.add_edge("prompt_review_enrich", "enrich")
    builder.add_edge("enrich", "prompt_review_detect")
    builder.add_edge("prompt_review_detect", "detect")
    builder.add_edge("detect", "ffmpeg")
    builder.add_edge("ffmpeg", "filter_clips")
    builder.add_edge("filter_clips", "renderer")
    builder.add_edge("renderer", END)

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["transcript_review", "prompt_review_enrich", "prompt_review_detect"],
    )