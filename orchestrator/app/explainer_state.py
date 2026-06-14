from typing import Optional, List
from typing_extensions import TypedDict


class ExplainerState(TypedDict):
    episode_id: str
    topic: str
    duration_minutes: Optional[int]
    style: Optional[str]
    avatar_image: Optional[str]

    # Script
    script_title: Optional[str]
    sections: Optional[List[dict]]
    script_prompt: Optional[str]

    # TTS outputs
    tts_sections: Optional[List[dict]]

    # B-roll outputs
    broll_sections: Optional[List[dict]]

    # Rendered sections
    rendered_sections: Optional[List[dict]]
    failed_sections: Optional[List[dict]]

    # Final
    final_video: Optional[str]
    pipeline_status: Optional[str]
    error: Optional[str]
