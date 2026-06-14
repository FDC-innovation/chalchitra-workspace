from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import httpx
import os
import asyncio
import subprocess
import tempfile

app = FastAPI()

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
PEXELS_URL = "https://api.pexels.com/videos/search"
SHARED = "/app/shared/volumes"


class BrollRequest(BaseModel):
    episode_id: str
    section_id: int
    keywords: List[str]
    duration_seconds: float
    orientation: Optional[str] = "landscape"


class BrollBatchRequest(BaseModel):
    episode_id: str
    sections: List[dict]


@app.get("/")
def health():
    return {"status": "broll running"}


async def fetch_video(keyword: str, orientation: str) -> Optional[dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            PEXELS_URL,
            headers={"Authorization": PEXELS_API_KEY},
            params={
                "query": keyword,
                "per_page": 10,
                "orientation": orientation,
                "size": "medium",
            },
            timeout=15,
        )
        if r.status_code != 200:
            return None

        data = r.json()
        videos = data.get("videos", [])

        for video in videos:
            files = video.get("video_files", [])
            hd = [f for f in files if f.get("quality") in ("hd", "sd") and f.get("width", 0) >= 720]
            if not hd:
                hd = files
            if hd:
                return {
                    "video_id": video["id"],
                    "keyword": keyword,
                    "url": hd[0]["link"],
                    "width": hd[0].get("width", 1280),
                    "height": hd[0].get("height", 720),
                    "duration": video.get("duration", 10),
                }
    return None


def transcode_clean(input_path: str, output_path: str) -> bool:
    """Transcode video to clean yuv420p removing any broken color metadata."""
    result = subprocess.run([
        "ffmpeg", "-y",
        "-i", input_path,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:a", "aac", "-ar", "44100",
        "-movflags", "+faststart",
        output_path
    ], capture_output=True)
    return result.returncode == 0


@app.post("/fetch")
async def fetch_broll(req: BrollRequest):
    if not PEXELS_API_KEY:
        raise HTTPException(500, "PEXELS_API_KEY not set")

    episode_dir = os.path.join(SHARED, req.episode_id)
    os.makedirs(episode_dir, exist_ok=True)

    result = None
    for keyword in req.keywords:
        result = await fetch_video(keyword, req.orientation)
        if result:
            break

    if not result:
        raise HTTPException(404, f"No b-roll found for keywords: {req.keywords}")

    output_path = os.path.join(episode_dir, f"section_{req.section_id:02d}_broll.mp4")
    tmp_path = output_path + ".raw.mp4"

    # Download raw
    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        r = await client.get(result["url"])
        with open(tmp_path, "wb") as f:
            f.write(r.content)

    # Transcode to clean format
    success = transcode_clean(tmp_path, output_path)

    # Cleanup temp
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    if not success or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise HTTPException(500, f"Failed to transcode b-roll for keyword: {result['keyword']}")

    return {
        "episode_id": req.episode_id,
        "section_id": req.section_id,
        "keyword_used": result["keyword"],
        "video_path": output_path,
        "duration": result["duration"],
        "width": result["width"],
        "height": result["height"],
    }


@app.post("/fetch_batch")
async def fetch_batch(req: BrollBatchRequest):
    tasks = [
        fetch_broll(BrollRequest(
            episode_id=req.episode_id,
            section_id=s["section_id"],
            keywords=s["keywords"],
            duration_seconds=s.get("duration_seconds", 10),
        ))
        for s in req.sections
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    successful = []
    failed = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            failed.append({"section_id": req.sections[i]["section_id"], "error": str(r)})
        else:
            successful.append(r)

    return {"fetched": successful, "failed": failed}