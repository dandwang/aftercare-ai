import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

import asyncpg
import httpx
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from redis.asyncio import Redis

from aftercare_api.config import Settings, get_settings

router = APIRouter(prefix="/health", tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["alive"]


class ServiceStatus(BaseModel):
    status: Literal["healthy", "unhealthy"]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    services: dict[str, ServiceStatus]


async def _check_postgres(settings: Settings) -> None:
    connection = await asyncpg.connect(settings.database_url)
    try:
        await connection.fetchval("SELECT 1")
    finally:
        await connection.close()


async def _check_redis(settings: Settings) -> None:
    client = Redis.from_url(settings.redis_url)
    try:
        if not await client.ping():
            raise RuntimeError("Redis ping did not return success")
    finally:
        await client.aclose()


async def _check_qdrant(settings: Settings) -> None:
    async with httpx.AsyncClient(timeout=settings.health_timeout_seconds) as client:
        response = await client.get(f"{settings.qdrant_url.rstrip('/')}/readyz")
        response.raise_for_status()


async def _run_probe(
    probe: Callable[[Settings], Awaitable[None]],
    settings: Settings,
) -> ServiceStatus:
    try:
        await asyncio.wait_for(probe(settings), timeout=settings.health_timeout_seconds)
    except (TimeoutError, OSError, RuntimeError, asyncpg.PostgresError, httpx.HTTPError):
        return ServiceStatus(status="unhealthy")
    return ServiceStatus(status="healthy")


async def get_dependency_statuses(
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, ServiceStatus]:
    names = ("postgres", "redis", "qdrant")
    probes = (_check_postgres, _check_redis, _check_qdrant)
    results = await asyncio.gather(*(_run_probe(probe, settings) for probe in probes))
    return dict(zip(names, results, strict=True))


@router.get("/live", response_model=LivenessResponse)
async def live() -> LivenessResponse:
    """Report whether the API process can serve requests."""

    return LivenessResponse(status="alive")


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def ready(
    services: Annotated[dict[str, ServiceStatus], Depends(get_dependency_statuses)],
) -> ReadinessResponse | JSONResponse:
    """Report whether required infrastructure dependencies are available."""

    is_ready = all(service.status == "healthy" for service in services.values())
    response = ReadinessResponse(
        status="ready" if is_ready else "not_ready",
        services=services,
    )
    if not is_ready:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=response.model_dump(),
        )
    return response

