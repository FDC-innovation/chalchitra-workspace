from typing import Optional, List
from typing_extensions import TypedDict


class ChalchitraState(TypedDict):
    episode_id: str
    file_path: str
    transcript_text: Optional[str]
    srt: Optional[str]
    words: Optional[list]
    title: Optional[str]
    show_notes: Optional[str]
    tags: Optional[list]
    chapters: Optional[list]
    detected_clips: Optional[List[dict]]
    cut_clips: Optional[List[dict]]
    approved_clips: Optional[List[dict]]
    human_feedback: Optional[str]
    rendered_clips: Optional[List[dict]]
    failed_clips: Optional[List[dict]]
    summary: Optional[dict]
    transcription_engine: Optional[str]
    pipeline_status: Optional[str]
    enrich_prompt: Optional[str]
    detect_prompt: Optional[str]
    error: Optional[str]
