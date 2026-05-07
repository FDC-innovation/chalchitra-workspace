from pydantic_settings import BaseSettings
from pathlib import Path

class Settings(BaseSettings):
    UPLOAD_DIR: Path = Path("/app/data")
    OUTPUT_DIR: Path = Path("/app/data")
    WHISPER_MODEL: str = "base"
    WHISPER_DEVICE: str = "cpu"
    MAX_CLIPS: int = 3
    ENABLE_RENDER: bool = True
    ANTHROPIC_API_KEY: str = ""
    OLLAMA_URL: str = "http://ollama:11434"
    LLM_BACKEND: str = "ollama"

    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()