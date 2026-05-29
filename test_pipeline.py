#!/usr/bin/env python3
import httpx
import time
import os
import sys
from datetime import datetime

ORCHESTRATOR_URL = "http://localhost:8007"
VIDEO_PATH = "/Users/adityakumartonk/Desktop/hindi_test_video.mp4"
POLL_INTERVAL = 60
TIMEOUT_MINUTES = 35

def log_status(timestamp, step, words_count, clips_found, clips_rendered, status):
    print(f"[{timestamp}] step={step} words={words_count} clips_found={clips_found} clips_rendered={clips_rendered} status={status}")

def main():
    if not os.path.exists(VIDEO_PATH):
        print(f"ERROR: Video file not found: {VIDEO_PATH}")
        sys.exit(1)

    episode_id = str(uuid.uuid4()) if 'uuid' in dir() else __import__('uuid').uuid4()
    episode_id = str(episode_id)
    
    start_time = time.time()
    timeout_seconds = TIMEOUT_MINUTES * 60

    # Step 1: Upload video to shared volumes
    print(f"[{datetime.now().isoformat()}] Copying video to shared volumes...")
    import shutil
    filename = f"{episode_id}.mp4"
    dest_path = f"./shared/volumes/{filename}"
    shutil.copy(VIDEO_PATH, dest_path)
    
    # Step 2: Start pipeline directly (bypass gateway)
    print(f"[{datetime.now().isoformat()}] Starting pipeline...")
    resp = httpx.post(
        f"{ORCHESTRATOR_URL}/pipeline/start",
        json={
            "episode_id": episode_id,
            "file_path": f"/app/shared/volumes/{filename}",
            "transcription_engine": "indic"
        },
        timeout=120,
    )
    
    if resp.status_code != 200:
        print(f"ERROR: Pipeline start failed: {resp.status_code} {resp.text}")
        sys.exit(1)
    
    print(f"[{datetime.now().isoformat()}] Pipeline started, episode_id={episode_id}")

    # Step 3: Poll status
    while time.time() - start_time < timeout_seconds:
        resp = httpx.get(f"{ORCHESTRATOR_URL}/pipeline/status/{episode_id}", timeout=30)
        if resp.status_code != 200:
            print(f"ERROR: Status check failed: {resp.status_code}")
            time.sleep(POLL_INTERVAL)
            continue

        state = resp.json()
        next_nodes = state.get("next", [])
        state_values = state.get("state", {})
        pipeline_status = state_values.get("pipeline_status", "")

        words_count = 0
        if state_values.get("transcript_text"):
            words_count = len(state_values["transcript_text"].split())

        clips_found = len(state_values.get("detected_clips") or [])
        clips_rendered = len(state_values.get("rendered_clips") or [])

        current_step = next_nodes[0] if next_nodes else "completed"

        log_status(
            datetime.now().isoformat(),
            current_step,
            words_count,
            clips_found,
            clips_rendered,
            pipeline_status
        )

        # HITL #1: Approve enrich
        if current_step == "enrich":
            print(f"[{datetime.now().isoformat()}] Auto-approving HITL #1 (enrich)...")
            httpx.post(
                f"{ORCHESTRATOR_URL}/pipeline/approve",
                json={"episode_id": episode_id, "approved_clips": []}
            )

        # HITL #2: Approve renderer
        elif current_step == "renderer":
            cut_clips = state_values.get("cut_clips") or []
            approved = []
            for c in cut_clips:
                file_path = c.get("file_path", "")
                if file_path:
                    approved.append({
                        "file_path": file_path,
                        "start_seconds": c.get("start_seconds", 0),
                        "end_seconds": c.get("end_seconds", 30),
                        "title": c.get("title", "clip")
                    })
            print(f"[{datetime.now().isoformat()}] Auto-approving HITL #2 (renderer) with {len(approved)} clips...")
            httpx.post(
                f"{ORCHESTRATOR_URL}/pipeline/approve",
                json={"episode_id": episode_id, "approved_clips": approved}
            )

        # Check completion
        if pipeline_status == "completed":
            print(f"\n[{datetime.now().isoformat()}] Pipeline completed!")
            rendered_clips = state_values.get("rendered_clips") or []
            rendered_paths = []
            for c in rendered_clips:
                path = c.get("rendered_clip") or c.get("output_path") or c.get("file_path")
                if path:
                    rendered_paths.append(path)
            
            print(f"\n=== SUMMARY ===")
            print(f"Episode ID: {episode_id}")
            print(f"Transcript word count: {words_count}")
            print(f"Number of clips: {clips_found}")
            print(f"Rendered files: {rendered_paths}")
            
            if rendered_paths:
                sys.exit(0)
            else:
                print("ERROR: No rendered clips found")
                sys.exit(1)

        time.sleep(POLL_INTERVAL)

    print(f"ERROR: Timeout after {TIMEOUT_MINUTES} minutes")
    sys.exit(1)

if __name__ == "__main__":
    main()