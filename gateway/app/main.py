from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import create_db
from app.api.routes import upload, episodes, jobs
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chalchitra")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Chalchitra starting up...")
    create_db()
    yield


app = FastAPI(title="Chalchitra", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router,   prefix="/api/upload",   tags=["Upload"])
app.include_router(episodes.router, prefix="/api/episodes", tags=["Episodes"])
app.include_router(jobs.router,     prefix="/api/jobs",     tags=["Jobs"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "chalchitra"}
