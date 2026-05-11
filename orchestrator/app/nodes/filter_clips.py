from app.state import ChalchitraState


async def filter_clips_node(state: ChalchitraState) -> dict:
    cut_clips = state.get("cut_clips") or []

    filtered = [
        clip for clip in cut_clips
        if (clip.get("end_seconds", 0) - clip.get("start_seconds", 0)) >= 15
    ]

    return {
        "cut_clips": filtered,
        "pipeline_status": "awaiting_approval",
    }
