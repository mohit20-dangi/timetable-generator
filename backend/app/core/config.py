import json
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central runtime configuration, loaded from environment / .env.

    Every institution-specific number that used to be a magic constant
    scattered through the code (max periods/day, default term length, etc.)
    lives here instead, so an operator can change it without a code change.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENVIRONMENT: str = "development"
    DATABASE_URL: str = "sqlite:///./timetable.db"

    JWT_SECRET_KEY: str = "dev-only-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 10080

    CORS_ORIGINS: str = '["http://localhost:5173","http://localhost:3000"]'

    # Optional AI features, served through any OpenAI-compatible chat
    # completions endpoint - OpenRouter, Ollama, NVIDIA NIM, OpenAI itself,
    # etc. Point LLM_BASE_URL at whichever provider you want; LLM_API_KEY
    # and LLM_MODEL follow that provider's own values. Left blank, features
    # degrade gracefully.
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://openrouter.ai/api/v1"
    LLM_MODEL: str = "anthropic/claude-opus-4.5"

    # Solver defaults. All overridable per constraint profile / request;
    # these are only the fallback when a caller doesn't specify.
    SOLVER_MAX_SECONDS: int = 300
    SOLVER_NUM_WORKERS: int = 8
    SOLVER_DEFAULT_ALTERNATIVES: int = 3

    @property
    def cors_origins_list(self) -> List[str]:
        try:
            parsed = json.loads(self.CORS_ORIGINS)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
        return ["http://localhost:5173"]


settings = Settings()
