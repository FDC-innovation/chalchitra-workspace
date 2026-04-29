FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip setuptools wheel

RUN pip install --no-cache-dir "numpy<2"

RUN pip install --no-cache-dir torch==2.1.2 \
    --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir git+https://github.com/openai/whisper.git

RUN pip install --no-cache-dir fastapi uvicorn pydantic

COPY app/ ./app/

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]