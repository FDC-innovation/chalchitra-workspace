from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    UPLOAD_DIR: Path = Path("/app/data")
    DATABASE_URL: str = "sqlite:////app/data/chalchitra.db"
    ANTHROPIC_API_KEY: str = ""
    N8N_WEBHOOK_URL: str = "http://n8n:5678/webhook-test/chalchitra"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
