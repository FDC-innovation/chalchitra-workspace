#!/bin/bash
TOPIC=$1
DURATION=${2:-3}
STYLE=${3:-professional}

if [ -z "$TOPIC" ]; then
  echo "Usage: ./run_explainer.sh \"your topic\" [duration_minutes] [style]"
  echo "Example: ./run_explainer.sh \"How AI is changing healthcare\" 3 professional"
  exit 1
fi

EPID=$(python3 -c "import uuid; print(uuid.uuid4())")
echo "Episode ID: $EPID"
echo "Topic: $TOPIC"
echo "Duration: ${DURATION} min | Style: $STYLE"
echo "---"

curl -s -X POST http://localhost:8007/explainer/start \
  -H "Content-Type: application/json" \
  -d "{
    \"topic\": \"$TOPIC\",
    \"duration_minutes\": $DURATION,
    \"style\": \"$STYLE\",
    \"episode_id\": \"$EPID\"
  }"

echo ""
echo "Episode ID: $EPID"
echo "Check status: curl -s http://localhost:8007/explainer/status/$EPID"
