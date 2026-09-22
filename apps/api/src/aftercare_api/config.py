from functools import lru_cache

from pydantic import Field, model_validator
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
    jwt_secret: str = "local-development-secret-change-before-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=30, gt=0, le=1440)

    @model_validator(mode="after")
    def reject_insecure_production_jwt_secret(self) -> "Settings":
        """Prevent the checked-in development secret from being used in production."""

        if self.environment == "production" and (
            self.jwt_secret == "local-development-secret-change-before-production"
            or len(self.jwt_secret) < 32
        ):
            raise ValueError("Production requires a unique JWT secret of at least 32 characters")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
