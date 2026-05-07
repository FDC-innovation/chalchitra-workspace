from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import create_db
from app.workers.queue import task_queue
from app.api.routes import upload, episodes, jobs, dashboard, enhance, remotion, steps, llm
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chalchitra")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Chalchitra starting up...")
    create_db()
    await task_queue.init()
    yield
    await task_queue.shutdown()

app = FastAPI(title="Chalchitra", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router,    prefix="/api/upload",    tags=["Upload"])
app.include_router(episodes.router,  prefix="/api/episodes",  tags=["Episodes"])
app.include_router(jobs.router,      prefix="/api/jobs",      tags=["Jobs"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(llm.router,       prefix="/api/llm",       tags=["LLM"])
app.include_router(enhance.router,   prefix="/api/enhance",   tags=["Enhance"])
app.include_router(remotion.router,  prefix="/api/render",    tags=["Render"])
app.include_router(steps.router)

# Serve rendered output files for download
app.mount("/files", StaticFiles(directory=str(settings.OUTPUT_DIR)), name="files")

# Serve the dashboard UI
@app.get("/", include_in_schema=False)
async def dashboard_ui():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))

@app.get("/health")
async def health():
    return {"status": "ok", "service": "chalchitra"}
