from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="AFTERCARE_",
        extra="ignore",
    )

    app_name: str = "AfterCare AI API"
    environment: str = "local"
    database_url: str = "postgresql://aftercare:aftercare@localhost:5432/aftercare"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    cors_origins: str = "http://localhost:5173"
    health_timeout_seconds: float = Field(default=2.0, gt=0, le=10)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

