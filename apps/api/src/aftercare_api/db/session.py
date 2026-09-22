"""Async SQLAlchemy session management."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aftercare_api.config import get_settings


def to_async_database_url(database_url: str) -> str:
    """Convert the existing PostgreSQL URL into SQLAlchemy's asyncpg dialect URL."""

    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return database_url


settings = get_settings()
engine = create_async_engine(to_async_database_url(settings.database_url), pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Provide one database session for each request."""

    async with SessionLocal() as session:
        yield session
