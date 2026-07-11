"""Application settings via pydantic-settings.

Every environment variable from SPEC.md section 4 is declared here with
its exact name. Defaults are sensible for development on the host Mac
only (Postgres published on 5433, Ollama native on 11434). The api
container always receives the real values from the compose environment,
so no default below is ever load-bearing in a deployed container.

The CHANGE_ME defaults mirror `.env.example` and are placeholders, not
secrets. `scripts/bootstrap_env.sh` generates real values into `.env`,
which is never committed.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All SPEC section 4 environment variables, names exact."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "postgresql://paritran_app:paritran@localhost:5433/paritran"
    POSTGRES_PASSWORD: str = "CHANGE_ME"
    JWT_SECRET: str = "CHANGE_ME"
    JWT_ACCESS_TTL_SECONDS: int = 900
    JWT_REFRESH_TTL_SECONDS: int = 28800
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "gemma3:4b"
    OLLAMA_TIMEOUT_SECONDS: int = 30
    INLEGALBERT_PATH: str = "/models/InLegalBERT"
    SEED: int = 42
    DEMO_MODE: bool = False
    SOUND_DEFAULT: str = "off"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance (cached)."""
    return Settings()
