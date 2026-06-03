#!/bin/bash
FILE=$1
EPID=$(python3 -c "import uuid; print(uuid.uuid4())")
mkdir -p shared/volumes/$EPID
cp "$FILE" shared/volumes/$EPID/source.mp4
curl -s -X POST http://localhost:8007/podcast/start \
  -H "Content-Type: application/json" \
  -d "{\"file_path\": \"/app/shared/volumes/$EPID/source.mp4\", \"episode_id\": \"$EPID\"}"
echo "\nEpisode ID: $EPID"
