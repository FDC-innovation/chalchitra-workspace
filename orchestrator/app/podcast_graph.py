from langgraph.graph import StateGraph, END
from app.podcast_state import PodcastState
from app.nodes.transcribe import transcribe_node          # reuse existing
from app.nodes.podcast_chapters import podcast_chapters_node
from app.nodes.podcast_cut import podcast_cut_node
from app.nodes.podcast_renderer import podcast_renderer_node


def build_podcast_graph(checkpointer):
    builder = StateGraph(PodcastState)

    # ── Nodes ────────────────────────────────────────────────────────────────
    builder.add_node("transcribe", transcribe_node)
    builder.add_node("chapters", podcast_chapters_node)
    builder.add_node("cut", podcast_cut_node)
    builder.add_node("renderer", podcast_renderer_node)

    # ── Edges ────────────────────────────────────────────────────────────────
    builder.set_entry_point("transcribe")
    builder.add_edge("transcribe", "chapters")
    builder.add_edge("chapters", "cut")      # interrupt_before="cut" in compile → HITL point
    builder.add_edge("cut", "renderer")
    builder.add_edge("renderer", END)

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["chapters"],
    )