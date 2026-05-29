#!/usr/bin/env python3
import httpx
import time
import os
import sys
import uuid
from datetime import datetime

ORCHESTRATOR_URL = "http://localhost:8007"
VIDEO_PATH = "/Users/adityakumartonk/Desktop/hindi_test_video.mp4"

def main():
    if not os.path.exists(VIDEO_PATH):
        print(f"ERROR: Video file not found: {VIDEO_PATH}")
        sys.exit(1)
    
    # Use first 30 seconds of video
    import subprocess
    short_video = "/tmp/short_demo.mp4"
    subprocess.run([
        "ffmpeg", "-i", VIDEO_PATH, "-t", "30", "-c:v", "libx264", "-c:a", "aac", "-y", short_video
    ], check=True, capture_output=True)
    print(f"Created short video: {short_video}")
    
    episode_id = str(uuid.uuid4())
    dest_path = f"/app/shared/volumes/{episode_id}.mp4"
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    os.system(f"cp {short_video} shared/volumes/{episode_id}.mp4")
    
    # Start pipeline
    print(f"[{datetime.now().isoformat()}] Starting pipeline...")
    start = time.time()
    
    # Use longer timeout
    with httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
        resp = client.post(
            f"{ORCHESTRATOR_URL}/pipeline/start",
            json={
                "episode_id": episode_id,
                "file_path": dest_path,
                "transcription_engine": "indic",
            },
        )
        
        if resp.status_code != 200:
            print(f"ERROR: {resp.status_code} {resp.text}")
            sys.exit(1)
        
        result = resp.json()
        elapsed = time.time() - start
        print(f"[{datetime.now().isoformat()}] Pipeline completed in {elapsed:.1f}s")
        print(f"Status: {result}")
        
        state = result.get("state", {})
        if state.get("transcript_text"):
            words = len(state["transcript_text"].split())
            print(f"Transcript words: {words}")
        
        rendered = state.get("rendered_clips", [])
        if rendered:
            print(f"Rendered clips: {len(rendered)}")

if __name__ == "__main__":
    main()