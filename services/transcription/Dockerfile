FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip && pip install --no-cache-dir \
    fastapi \
    uvicorn \
    openai-whisper \
    torch \
    torchaudio \
    --extra-index-url https://download.pytorch.org/whl/cpu

COPY app/ ./app/

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
