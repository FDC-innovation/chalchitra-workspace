import json, urllib.request, time

EPISODE_ID = "3d027c5d-728b-44c8-a342-565817aa5b30"
VOL = f"/app/shared/volumes/{EPISODE_ID}"

# Exact titles to render. Empty list = render ALL 26.
KEEP = [
]

clips = json.load(open("detected_clips_v2.json"))["clips"]
words = json.load(open("words.json"))
if KEEP:
    missing = [t for t in KEEP if t not in {c["title"] for c in clips}]
    if missing:
        raise SystemExit(f"Titles not found in detected_clips_v2.json: {missing}")
    clips = [c for c in clips if c["title"] in KEEP]
print(f"Rendering {len(clips)} clips")

def safe(t):
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in t)[:40]

rendered, failed = [], []
for j, clip in enumerate(clips):
    clip_path = f"{VOL}/{EPISODE_ID}_clip0_{safe(clip['title'])}.mp4"
    t0 = time.time()
    try:
        req = urllib.request.Request("http://localhost:8006/render",
            data=json.dumps({
                "episode_id": EPISODE_ID,
                "clip_path": clip_path,
                "title": clip["title"],
                "start_seconds": clip["start_seconds"],
                "end_seconds": clip["end_seconds"],
                "words": words,
                "channel_name": "Chalchitra",
                "cta_text": "Follow for more",
            }).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=36000) as r:
            res = json.load(r)
        rendered.append(res)
        print(f"[{j+1}/{len(clips)}] ok {(time.time()-t0)/60:.1f}min  {clip['title']} -> {res.get('rendered_clip')}", flush=True)
    except Exception as e:
        failed.append({"title": clip["title"], "clip_path": clip_path, "error": str(e)})
        print(f"[{j+1}/{len(clips)}] FAILED  {clip['title']}: {e}", flush=True)

json.dump({"rendered": rendered, "failed": failed}, open("render_results.json","w"), indent=2)
print(f"\nDONE: {len(rendered)} rendered, {len(failed)} failed", flush=True)
