from langgraph.graph import StateGraph, END
from app.state import ChalchitraState
from app.nodes.transcribe import transcribe_node
from app.nodes.enrich import enrich_node
from app.nodes.detect import detect_node
from app.nodes.ffmpeg import ffmpeg_node
from app.nodes.filter_clips import filter_clips_node
from app.nodes.renderer import renderer_node


def build_graph(checkpointer):
    builder = StateGraph(ChalchitraState)

    builder.add_node("transcribe", transcribe_node)
    builder.add_node("enrich", enrich_node)
    builder.add_node("detect", detect_node)
    builder.add_node("ffmpeg", ffmpeg_node)
    builder.add_node("filter_clips", filter_clips_node)
    builder.add_node("renderer", renderer_node)

    builder.set_entry_point("transcribe")
    builder.add_edge("transcribe", "enrich")
    builder.add_edge("enrich", "detect")
    builder.add_edge("detect", "ffmpeg")
    builder.add_edge("ffmpeg", "filter_clips")
    builder.add_edge("filter_clips", "renderer")
    builder.add_edge("renderer", END)

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["enrich", "renderer"],
    )
