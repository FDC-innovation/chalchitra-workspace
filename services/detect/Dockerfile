FROM python:3.11-slim

WORKDIR /app

RUN pip install --upgrade pip && pip install --no-cache-dir \
    fastapi \
    uvicorn \
    anthropic

COPY app/ ./app/

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
