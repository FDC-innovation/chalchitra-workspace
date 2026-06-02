FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-dejavu-core \
    fonts-noto \
    fonts-noto-extra \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -fv
RUN pip install --upgrade pip && pip install --no-cache-dir \
    fastapi uvicorn pydantic Pillow
COPY app/ ./app/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8006"]
