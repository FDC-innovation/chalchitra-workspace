from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import subprocess
import os

app = FastAPI()


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

        cmd = [
            "ffmpeg", "-y",
            "-i", req.file_path,
            "-ss", str(start),
            "-t", str(duration),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-avoid_negative_ts", "make_zero",
            output_path
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True)
            generated.append({
                **clip,
                "file_path": output_path,
                "status": "done"
            })
        except subprocess.CalledProcessError as e:
            generated.append({
                **clip,
                "status": "failed",
                "error": e.stderr.decode()
            })

    return {
        "episode_id": req.episode_id,
        "clips": generated,
    }