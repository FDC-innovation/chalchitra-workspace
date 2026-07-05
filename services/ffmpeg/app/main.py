from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import subprocess
import os

app = FastAPI()

MAX_CLIP_DURATION = 90


class ClipRequest(BaseModel):
    episode_id: str
    file_path: str
    clips: list


@app.get("/")
def health():
    return {"status": "ffmpeg service running"}


@app.post("/ffmpeg")
def generate_clips(req: ClipRequest):
    if not os.path.exists(req.file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {req.file_path}")

    output_dir = os.path.dirname(req.file_path)
    generated = []

    for i, clip in enumerate(req.clips):
        start = clip.get("start_seconds", 0)
        end = clip.get("end_seconds", 30)
        title = clip.get("title", f"clip_{i}")
        duration = end - start

        safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in title)[:40]
        output_path = os.path.join(output_dir, f"{req.episode_id}_clip{i}_{safe_title}.mp4")

        coarse = max(0, start - 5)
        fine = start - coarse
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(coarse),
            "-i", req.file_path,
            "-ss", str(fine),
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-r", "30",
            "-c:a", "aac", "-ar", "44100",
            "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart",
            output_path
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True)
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries",
                 "format=duration", "-of", "csv=p=0", output_path],
                capture_output=True, text=True
            )
            if probe.returncode != 0 or not probe.stdout.strip():
                generated.append({**clip, "status": "failed", "error": "Output not seekable"})
            else:
                generated.append({**clip, "file_path": output_path, "status": "done"})
        except subprocess.CalledProcessError as e:
            generated.append({**clip, "status": "failed", "error": e.stderr.decode()})

    return {"episode_id": req.episode_id, "clips": generated}

class DurationRequest(BaseModel):
    file_path: str

@app.post("/duration")
def get_duration(req: DurationRequest):
    if not os.path.exists(req.file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {req.file_path}")
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries",
         "format=duration", "-of", "csv=p=0", req.file_path],
        capture_output=True, text=True
    )
    if probe.returncode != 0 or not probe.stdout.strip():
        raise HTTPException(status_code=500, detail="Could not read duration")
    return {"duration": float(probe.stdout.strip())}
