# Chalchitra Clips Pipeline — Runbook

End-to-end guide for generating short clips from a long-form video.
Last validated: 2026-07-05 (SellSide x Sandeep Goyal, 90 min / 11.5 GB → 26 clips).

## Architecture

gateway :8000 → orchestrator :8007 (LangGraph, SQLite checkpoints)
    transcribe → [interrupt] → enrich → detect → filter_clips → ffmpeg → renderer
services: detect :8003 | ffmpeg :8004 | renderer :8006 | enrich :8002 | ollama :11434

## Constraints (8GB Mac, Docker VM ~3.8GB)

- Ollama (llama3.2:latest, 2GB) needs headroom. While detect runs, STOP heavy containers:
  docker stop chalchitra-transcription chalchitra-podcast-renderer
- After detect completes, stop Ollama before rendering:
  docker stop chalchitra-ollama
- detect & ffmpeg code is BAKED INTO IMAGES. After any edit:
  docker compose build <service> && docker compose up -d --force-recreate <service>
  Verify: docker exec <container> grep -n "<your change>" /app/app/main.py

## Normal pipeline run (orchestrated)

1. docker compose up -d && docker start chalchitra-ollama chalchitra-transcription
2. curl -X POST http://localhost:8007/pipeline/start \
     -H "Content-Type: application/json" \
     -d '{"file_path": "/app/shared/volumes/<episode>/source.mp4"}'
3. Graph pauses BEFORE enrich. Resume with clip prompt:
   curl -X POST http://localhost:8007/pipeline/resume_transcript \
     -H "Content-Type: application/json" \
     -d '{"episode_id": "<id>", "custom_prompt": "<instructions incl. between 30 and 90 seconds>"}'
4. Status: curl http://localhost:8007/pipeline/status/<episode_id>
5. Outputs in /app/shared/volumes/<episode_id>/:
   raw cuts *_clip0_<Title>.mp4, finals <Title>_final.mp4

NOTE: orchestrator's detect_node does not yet pass `words` to detect (see TODO) —
orchestrated runs use estimate-mode timestamps. Use the manual flow for best quality.

## Manual flow (produced the 26-clip batch)

Assumes transcription completed and state exists for <EPISODE_ID>.

1. Extract transcript + words from state:
   curl -s http://localhost:8007/pipeline/status/$EP | python3 -c \
     "import json,sys; s=json.load(sys.stdin)['state']; \
      open('transcript.txt','w').write(s['transcript_text']); \
      json.dump(s.get('words') or [], open('words.json','w'))"
2. Detect (words mode, real timestamps, ~30-45 min for 90-min episode):
   POST localhost:8003/detect {episode_id, transcript, words, system_prompt}
   Save response as detected_clips_v2.json. Logs must show MODE=words.
3. Cut (fast seek ~50s/clip): POST per clip to localhost:8004/ffmpeg
   {episode_id, file_path: /app/shared/volumes/$EP/source.mp4, clips:[clip], clip_index:i}
4. Review raw cuts, stop ollama, then: python3 run_render.py (edit KEEP; empty = all)
5. Copy finals:
   docker exec chalchitra-ffmpeg sh -c "ls /app/shared/volumes/$EP/*_final.mp4" \
     | while read f; do docker cp "chalchitra-ffmpeg:$f" ~/Desktop/finals/; done

## Key implementation notes

- detect words-mode: sentences from word timestamps (punct + >=0.6s pauses),
  ~5500-char chunks with real [t=NNNs] markers, bounds snapped to sentences,
  retries on Ollama 5xx and malformed JSON.
- duration parsing: "between X and Y seconds" from prompt; filter tolerance ±15%.
- ffmpeg: two-stage seek (-ss coarse before -i, fine -ss after). Do NOT revert
  to -ss after -i (linear slowdown on long files).
- ffmpeg naming: {episode_id}_clip{i}_{safe_title[:40]}.mp4, safe_title keeps
  alnum + -_. Request clip_index is NOT used in filenames.
- renderer payload: {episode_id, clip_path, title, start_seconds, end_seconds,
  words, channel_name, cta_text} → <Title>_final.mp4 (reframe/captions/cards).

## Fixed in this branch (2026-07-05)

1. detect: Groq → local Ollama (httpx), full-transcript chunking (was [:6000])
2. detect: duration regex no longer matches unrelated "2-3 seconds" phrases
3. detect: robust JSON extraction (raw_decode + find('{'))
4. detect: prompts fixed to prevent placeholder-title echo
5. detect: words-mode with real timestamps + sentence snapping + retries
6. detect Dockerfile: ENV PYTHONUNBUFFERED=1
7. ffmpeg: two-stage fast seek (~8 min → ~50 s per deep clip)

## TODO

- [ ] orchestrator/app/nodes/detect.py: add "words": state.get("words") or []
      to detect payload, rebuild orchestrator (enables words-mode in graph runs)
- [ ] enrich still truncates to [:4000] (acceptable — metadata only)
- [ ] no "redo one node" endpoint; completed graphs can't be resumed
