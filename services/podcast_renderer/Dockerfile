FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY app/main.py app/main.py
RUN pip install --no-cache-dir fastapi uvicorn pydantic

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8009"]