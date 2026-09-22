from fastapi.testclient import TestClient

from aftercare_api.health import ServiceStatus, get_dependency_statuses
from aftercare_api.main import app

client = TestClient(app)


async def healthy_dependencies() -> dict[str, ServiceStatus]:
    return {
        "postgres": ServiceStatus(status="healthy"),
        "redis": ServiceStatus(status="healthy"),
        "qdrant": ServiceStatus(status="healthy"),
    }


async def unhealthy_dependencies() -> dict[str, ServiceStatus]:
    return {
        "postgres": ServiceStatus(status="healthy"),
        "redis": ServiceStatus(status="healthy"),
        "qdrant": ServiceStatus(status="unhealthy"),
    }


def test_liveness_does_not_require_infrastructure() -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_succeeds_when_all_dependencies_are_healthy() -> None:
    app.dependency_overrides[get_dependency_statuses] = healthy_dependencies
    try:
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readiness_fails_when_a_required_dependency_is_unhealthy() -> None:
    app.dependency_overrides[get_dependency_statuses] = unhealthy_dependencies
    try:
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "services": {
            "postgres": {"status": "healthy"},
            "redis": {"status": "healthy"},
            "qdrant": {"status": "unhealthy"},
        },
    }

