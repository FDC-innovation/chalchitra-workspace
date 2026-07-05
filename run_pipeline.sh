#!/bin/bash
# Chalchitra one-shot pipeline runner
# Usage: ./run_pipeline.sh ~/Videos/my-episode.mp4
set -euo pipefail

MAC_VIDEO="${1:?Usage: ./run_pipeline.sh <path-to-video-on-your-mac> [prompt_file] [output_dir]}"
PROMPT_FILE="${2:-clip_prompt.txt}"
OUT_DIR="${3:-$HOME/Desktop/finals-$(date +%Y%m%d-%H%M)}"
ORCH="http://localhost:8007"

[ -f "$MAC_VIDEO" ] || { echo "Video not found: $MAC_VIDEO"; exit 1; }
[ -f "$PROMPT_FILE" ] || { echo "Prompt file not found: $PROMPT_FILE"; exit 1; }

log() { echo "[$(date +%H:%M:%S)] $*"; }

# ---- Phase 0: copy video into the shared volume ----
FOLDER="ep-$(date +%Y%m%d-%H%M%S)"
CONTAINER_PATH="/app/shared/volumes/$FOLDER/source.mp4"
log "Phase 0: copying video into shared volume ($FOLDER) — big files take a few minutes"
docker exec chalchitra-ffmpeg mkdir -p "/app/shared/volumes/$FOLDER"
docker cp "$MAC_VIDEO" "chalchitra-ffmpeg:$CONTAINER_PATH"
log "Video in place: $CONTAINER_PATH"

# ---- Phase 1: RAM setup for transcription ----
log "Phase 1: preparing containers for transcription"
docker stop chalchitra-ollama chalchitra-podcast-renderer 2>/dev/null || true
docker start chalchitra-transcription
sleep 5

# ---- Phase 2: start pipeline (blocks through transcription) ----
log "Phase 2: transcribing (roughly real-time; a 90-min video takes a long while)"
START_RESP=$(curl -s --max-time 36000 -X POST "$ORCH/pipeline/start" \
  -H "Content-Type: application/json" \
  -d "{\"file_path\": \"$CONTAINER_PATH\", \"transcription_engine\": \"indic\"}")
EPISODE_ID=$(echo "$START_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['episode_id'])")
log "Transcription done (episode $EPISODE_ID), graph paused"

# ---- Phase 3: swap containers for LLM work ----
log "Phase 3: swapping containers (transcription off, ollama on)"
docker stop chalchitra-transcription
docker start chalchitra-ollama
until curl -s http://localhost:11434/api/tags > /dev/null 2>&1; do sleep 5; done
log "Ollama ready"

# ---- Phase 4: resume with the clip prompt ----
PROMPT=$(python3 -c "import json; print(json.dumps(open('$PROMPT_FILE').read().strip()))")
log "Phase 4: resuming (enrich -> detect -> cut -> render)"
curl -s --max-time 36000 -X POST "$ORCH/pipeline/resume_transcript" \
  -H "Content-Type: application/json" \
  -d "{\"episode_id\": \"$EPISODE_ID\", \"custom_prompt\": $PROMPT}" > /dev/null

# ---- Phase 5: poll until completed ----
log "Phase 5: polling every 60s (detect ~40min, then ~2.5min per clip render)"
while true; do
  STATUS=$(curl -s "$ORCH/pipeline/status/$EPISODE_ID")
  PSTATUS=$(echo "$STATUS" | python3 -c "import json,sys; s=json.load(sys.stdin); print(s['state'].get('pipeline_status','running'), len(s.get('next',[])))" 2>/dev/null || echo "unknown 1")
  read -r PS NEXT_COUNT <<< "$PSTATUS"
  log "  status=$PS pending_nodes=$NEXT_COUNT"
  if [ "$PS" = "completed" ] && [ "$NEXT_COUNT" = "0" ]; then break; fi
  if [ "$PS" = "failed" ]; then log "PIPELINE FAILED — check docker logs"; exit 1; fi
  sleep 60
done
log "Pipeline completed"

# ---- Phase 6: collect finals ----
log "Phase 6: copying finals to $OUT_DIR"
docker stop chalchitra-ollama 2>/dev/null || true
mkdir -p "$OUT_DIR"
docker exec chalchitra-ffmpeg sh -c "ls /app/shared/volumes/$EPISODE_ID/*_final.mp4 2>/dev/null || ls /app/shared/volumes/$FOLDER/*_final.mp4" | \
  while read -r f; do docker cp "chalchitra-ffmpeg:$f" "$OUT_DIR/"; done
COUNT=$(ls "$OUT_DIR"/*_final.mp4 2>/dev/null | wc -l | tr -d ' ')
log "DONE — $COUNT final clips in $OUT_DIR"
open "$OUT_DIR"
