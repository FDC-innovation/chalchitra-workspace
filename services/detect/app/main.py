from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Tuple, List, Dict, Any
import os
import json
import re
import time
import httpx

app = FastAPI()

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434") + "/api/generate"
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:latest")

SENT_END = (".", "?", "!")
PAUSE = 0.6
MARKER_GAP = 8.0        # seconds between [t=..] markers
CHUNK_CHARS = 5500


class DetectRequest(BaseModel):
    episode_id: str
    transcript: str
    srt: Optional[str] = ""
    system_prompt: Optional[str] = None
    words: Optional[List[Dict[str, Any]]] = None


def parse_duration_range(text: str) -> Tuple[Optional[float], Optional[float]]:
    m = re.search(
        r'(?:clip[s]?|each|duration|long|between)\D{0,20}?(\d+)\s*(?:and|[-–to]+)\s*(\d+)\s*s(?:ec(?:onds?)?)?',
        text, re.I
    )
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(
        r'(?:clip[s]?|each|duration|long|between)\D{0,20}?(\d+(?:\.\d+)?)\s*(?:and|[-–to]+)\s*(\d+(?:\.\d+)?)\s*min(?:utes?)?',
        text, re.I
    )
    if m:
        return float(m.group(1)) * 60, float(m.group(2)) * 60
    return None, None


def build_sentences(words: List[dict]) -> List[dict]:
    """Group word-level timestamps into sentences using punctuation and pauses."""
    sentences = []
    cur = []
    for i, w in enumerate(words):
        cur.append(w)
        token = str(w.get("word", "")).rstrip('"').rstrip("'")
        is_end = token.endswith(SENT_END)
        if not is_end and i + 1 < len(words):
            try:
                if float(words[i + 1]["start"]) - float(w["end"]) >= PAUSE:
                    is_end = True
            except (TypeError, ValueError, KeyError):
                pass
        if is_end or i == len(words) - 1:
            sentences.append({
                "text": " ".join(str(x.get("word", "")) for x in cur),
                "start": float(cur[0]["start"]),
                "end": float(cur[-1]["end"]),
            })
            cur = []
    return sentences


def chunk_sentences(sentences: List[dict], chunk_chars: int = CHUNK_CHARS) -> List[List[dict]]:
    chunks, cur, cur_len = [], [], 0
    for s in sentences:
        if cur and cur_len + len(s["text"]) > chunk_chars:
            chunks.append(cur)
            cur, cur_len = [], 0
        cur.append(s)
        cur_len += len(s["text"]) + 1
    if cur:
        chunks.append(cur)
    return chunks


def render_chunk_text(chunk: List[dict]) -> str:
    """Sentences with real [t=..s] time markers injected."""
    parts = []
    last_marker = -1e9
    for s in chunk:
        if s["start"] - last_marker >= MARKER_GAP:
            parts.append(f"[t={int(s['start'])}s]")
            last_marker = s["start"]
        parts.append(s["text"])
    return " ".join(parts)


def snap_to_sentences(start: float, end: float, sentences: List[dict]) -> Tuple[float, float]:
    """Snap clip bounds to real sentence boundaries."""
    s_start = min(sentences, key=lambda s: abs(s["start"] - start))["start"]
    candidates_end = [s for s in sentences if s["end"] > s_start]
    if not candidates_end:
        return s_start, end
    s_end = min(candidates_end, key=lambda s: abs(s["end"] - end))["end"]
    return round(s_start, 2), round(s_end + 0.15, 2)


def call_ollama(prompt: str, system: str, retries: int = 2) -> str:
    full_prompt = f"{system}\n\n{prompt}"
    last_err = None
    for attempt in range(retries + 1):
        try:
            response = httpx.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {"num_predict": 1500, "temperature": 0.3},
                },
                timeout=600,
            )
            response.raise_for_status()
            return response.json()["response"].strip()
        except httpx.HTTPStatusError as e:
            last_err = e
            if e.response.status_code >= 500 and attempt < retries:
                print(f"[detect] ollama 5xx, retrying in 15s (attempt {attempt+1}/{retries})", flush=True)
                time.sleep(15)
                continue
            raise
    raise last_err


def parse_clips_json(text: str) -> List[dict]:
    text = text.replace('```json', '').replace('```', '').strip()
    start_idx = text.find('{')
    if start_idx == -1:
        raise ValueError("No JSON object found in model output")
    data, _ = json.JSONDecoder().raw_decode(text[start_idx:])
    return data.get("clips", [])


@app.get("/")
def health():
    return {"status": "detect service running"}


@app.post("/detect")
def detect(req: DetectRequest):
    if not req.transcript.strip() and not req.words:
        raise HTTPException(400, "Empty transcript")

    system = "You are a professional video editor. Return ONLY valid JSON, no markdown, no explanation."

    user_min, user_max = (None, None)
    if req.system_prompt:
        user_min, user_max = parse_duration_range(req.system_prompt)

    use_words = bool(req.words)
    sentences = build_sentences(req.words) if use_words else []

    if use_words:
        total_duration = sentences[-1]["end"]
        chunks = chunk_sentences(sentences)
        print(f"[detect] episode={req.episode_id} MODE=words sentences={len(sentences)} chunks={len(chunks)} duration={total_duration:.0f}s", flush=True)
    else:
        total_word_count = len(req.transcript.split())
        total_duration = total_word_count / 2.5
        raw_chunks = []
        remaining = req.transcript
        while remaining:
            if len(remaining) <= CHUNK_CHARS:
                raw_chunks.append(remaining)
                break
            cut = remaining.rfind('. ', 0, CHUNK_CHARS)
            if cut == -1:
                cut = CHUNK_CHARS
            raw_chunks.append(remaining[:cut + 1])
            remaining = remaining[cut + 1:]
        chunks = raw_chunks
        print(f"[detect] episode={req.episode_id} MODE=estimate chunks={len(chunks)} est_duration={total_duration:.0f}s", flush=True)

    print(f"[detect] parsed duration range from prompt: min={user_min} max={user_max}", flush=True)

    lo = user_min if user_min else 20
    hi = user_max if user_max else 90

    all_clips = []
    chars_seen = 0
    chars_per_second = (len(req.transcript) / max(total_duration, 1)) if req.transcript else 1

    for i, chunk in enumerate(chunks):
        if use_words:
            chunk_text = render_chunk_text(chunk)
            c_start, c_end = int(chunk[0]["start"]), int(chunk[-1]["end"])
            timing_block = f"""This segment runs from {c_start}s to {c_end}s of the full video. The [t=NNNs] markers in the text are REAL timestamps of the words that follow them.
- start_seconds MUST be the value of a [t=NNNs] marker where a strong moment begins.
- end_seconds MUST be start_seconds + a duration between {lo:.0f} and {hi:.0f} seconds, and must not exceed {c_end}.
- Do NOT invent timestamps. Only use times visible in the markers."""
        else:
            time_offset = chars_seen / chars_per_second if chars_per_second else 0
            chars_seen += len(chunk)
            chunk_text = chunk
            timing_block = f"This segment starts at {time_offset:.0f}s in the full video. Add {time_offset:.0f} to any position within this segment. Every clip must be between {lo:.0f} and {hi:.0f} seconds long."

        instructions = req.system_prompt or "Find the 0-3 most engaging, self-contained clip-worthy moments."

        prompt = f"""Find clip-worthy moments in this transcript segment.

USER INSTRUCTIONS (follow exactly):
{instructions}

TIMING RULES:
{timing_block}

Transcript segment:
{chunk_text}

Return ONLY valid JSON — do NOT copy the example values, write real titles and timestamps based on the transcript content:
{{
  "clips": [
    {{
      "title": "<write a real punchy title here, max 6 words>",
      "start_seconds": <number>,
      "end_seconds": <number>,
      "reason": "<why this works as a standalone clip>"
    }}
  ]
}}"""

        text = ""
        for attempt in range(2):
            try:
                text = call_ollama(prompt, system)
                print(f"[detect] chunk {i} raw model output (first 400 chars): {text[:400]}", flush=True)
                chunk_clips = parse_clips_json(text)
                print(f"[detect] chunk {i} parsed {len(chunk_clips)} clips", flush=True)
                all_clips.extend(chunk_clips)
                break
            except (json.JSONDecodeError, ValueError) as e:
                print(f"[detect] chunk {i} JSON parse failed (attempt {attempt+1}/2): {e}", flush=True)
                if attempt == 1:
                    print(f"[detect] chunk {i} SKIPPED after retries", flush=True)
            except Exception as e:
                print(f"[detect] chunk {i} FAILED: {type(e).__name__}: {e}", flush=True)
                break

    print(f"[detect] total raw clips: {len(all_clips)}", flush=True)

    min_dur, max_dur = lo * 0.85, hi * 1.15
    print(f"[detect] filtering with min_dur={min_dur:.1f} max_dur={max_dur:.1f}", flush=True)

    valid_clips = []
    for clip in all_clips:
        try:
            start = float(clip.get("start_seconds", 0))
            end = float(clip.get("end_seconds", 0))
        except (TypeError, ValueError):
            continue
        if use_words:
            start, end = snap_to_sentences(start, end, sentences)
        duration = end - start
        if min_dur <= duration <= max_dur and start >= 0 and end <= total_duration + 1:
            valid_clips.append({
                "title": clip.get("title", f"Clip {len(valid_clips)+1}"),
                "start_seconds": start,
                "end_seconds": end,
                "reason": clip.get("reason", ""),
            })
        else:
            print(f"[detect] rejected clip: start={start} end={end} duration={duration:.1f} title={clip.get('title','')[:40]}", flush=True)

    valid_clips.sort(key=lambda c: c["start_seconds"])
    non_overlapping = []
    last_end = -1
    for clip in valid_clips:
        if clip["start_seconds"] >= last_end:
            non_overlapping.append(clip)
            last_end = clip["end_seconds"]

    print(f"[detect] final non-overlapping valid clips: {len(non_overlapping)}", flush=True)

    if not non_overlapping:
        clip_end = min(60, total_duration)
        if clip_end >= 5:
            non_overlapping.append({
                "title": "Key Moment",
                "start_seconds": 0,
                "end_seconds": clip_end,
                "reason": "Best available segment",
            })

    if not non_overlapping:
        raise HTTPException(500, "Video too short to create clips")

    return {
        "episode_id": req.episode_id,
        "clips": non_overlapping,
        "total_clips": len(non_overlapping),
    }
