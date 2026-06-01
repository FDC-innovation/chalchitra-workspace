FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    fonts-liberation2 \
    fonts-open-sans \
    fontconfig \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

# Download Anton (impact-style headline font) and Montserrat ExtraBold
COPY fonts/ /usr/share/fonts/truetype/custom/
RUN fc-cache -fv

RUN pip install --upgrade pip

RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    pydantic \
    pillow \
    numpy \
    opencv-python-headless

COPY app/ ./app/

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
