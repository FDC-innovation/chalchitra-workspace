from typing import Optional, List
from typing_extensions import TypedDict


class PodcastState(TypedDict):
    episode_id: str
    file_path: str
    transcript_text: Optional[str]
    srt: Optional[str]
    words: Optional[list]
    chapters: Optional[list]
    chapter_clips: Optional[List[dict]]
    rendered_chapters: Optional[List[dict]]
    failed_chapters: Optional[List[dict]]
    final_video: Optional[str]
    transcription_engine: Optional[str]
    pipeline_status: Optional[str]
    chapters_prompt: Optional[str]   # human-editable chapters prompt
    error: Optional[str]