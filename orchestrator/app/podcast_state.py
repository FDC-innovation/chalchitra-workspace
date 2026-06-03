from typing import Optional, List
from typing_extensions import TypedDict


class PodcastState(TypedDict):
    episode_id: str
    file_path: str
    transcription_engine: Optional[str]

    # transcription outputs (reused from transcribe_node)
    transcript_text: Optional[str]
    srt: Optional[str]
    words: Optional[list]

    # chapter enrich outputs
    title: Optional[str]
    show_notes: Optional[str]
    tags: Optional[list]
    chapters: Optional[list]          # [{title, subtitle, start_seconds, end_seconds}]

    # cut chapter clips
    chapter_clips: Optional[List[dict]]  # [{title, subtitle, start_seconds, end_seconds, file_path}]

    # rendered chapters + final stitch
    rendered_chapters: Optional[List[dict]]
    failed_chapters: Optional[List[dict]]
    final_video: Optional[str]

    # human-in-the-loop
    human_feedback: Optional[str]

    pipeline_status: Optional[str]
    error: Optional[str]