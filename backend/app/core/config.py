from pydantic_settings import BaseSettings
from typing import Optional
import os

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./timetable.db"
    NVIDIA_API_KEY: Optional[str] = None
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    NVIDIA_MODEL: str = "meta/llama-3.1-70b-instruct"
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()