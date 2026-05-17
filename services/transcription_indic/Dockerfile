FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install --upgrade pip
RUN pip install --no-cache-dir fastapi uvicorn
RUN pip install --no-cache-dir ctranslate2
RUN pip install --no-cache-dir faster-whisper
COPY app/ ./app/
EXPOSE 8011
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8011"]
