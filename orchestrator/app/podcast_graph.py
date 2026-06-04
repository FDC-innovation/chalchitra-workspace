from langgraph.graph import StateGraph, END
from app.podcast_state import PodcastState
from app.nodes.transcribe import transcribe_node
from app.nodes.podcast_chapters import podcast_chapters_node
from app.nodes.podcast_cut import podcast_cut_node
from app.nodes.podcast_renderer import podcast_renderer_node


async def transcript_review_node(state: PodcastState) -> dict:
    """No-op — pause for human transcript review."""
    return {}


async def prompt_review_chapters_node(state: PodcastState) -> dict:
    """No-op — pause for human to edit chapters prompt."""
    return {}


def build_podcast_graph(checkpointer):
    builder = StateGraph(PodcastState)

    builder.add_node("transcribe", transcribe_node)
    builder.add_node("transcript_review", transcript_review_node)
    builder.add_node("prompt_review_chapters", prompt_review_chapters_node)
    builder.add_node("chapters", podcast_chapters_node)
    builder.add_node("cut", podcast_cut_node)
    builder.add_node("renderer", podcast_renderer_node)

    builder.set_entry_point("transcribe")
    builder.add_edge("transcribe", "transcript_review")
    builder.add_edge("transcript_review", "prompt_review_chapters")
    builder.add_edge("prompt_review_chapters", "chapters")
    builder.add_edge("chapters", "cut")
    builder.add_edge("cut", "renderer")
    builder.add_edge("renderer", END)

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["transcript_review", "prompt_review_chapters"],
    )