from langgraph.graph import StateGraph, END
from app.explainer_state import ExplainerState
from app.nodes.explainer_script import explainer_script_node
from app.nodes.explainer_tts import explainer_tts_node
from app.nodes.explainer_broll import explainer_broll_node
from app.nodes.explainer_render import explainer_render_node


async def script_review_node(state: ExplainerState) -> dict:
    """Pause point — human reviews/edits script before TTS."""
    return {}


def build_explainer_graph(checkpointer):
    builder = StateGraph(ExplainerState)

    builder.add_node("script", explainer_script_node)
    builder.add_node("script_review", script_review_node)
    builder.add_node("tts", explainer_tts_node)
    builder.add_node("broll", explainer_broll_node)
    builder.add_node("renderer", explainer_render_node)

    builder.set_entry_point("script")
    builder.add_edge("script", "script_review")
    builder.add_edge("script_review", "tts")
    builder.add_edge("tts", "broll")
    builder.add_edge("broll", "renderer")
    builder.add_edge("renderer", END)

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["script_review"],
    )
