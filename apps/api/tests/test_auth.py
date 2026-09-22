import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aftercare_api.config import Settings, get_settings
from aftercare_api.db.base import Base
from aftercare_api.db.session import get_session
from aftercare_api.identity.models import Tenant, TenantMembership, User
from aftercare_api.main import app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[tuple[TestClient, async_sessionmaker[AsyncSession]]]:
    database_path = tmp_path / "auth.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def create_tables() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_tables())

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client, session_factory
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def register(client: TestClient, email: str = "admin@example.com") -> str:
    response = client.post(
        "/api/v1/auth/register-tenant-admin",
        json={
            "tenant_name": "Example Store",
            "tenant_slug": "example-store",
            "email": email,
            "password": "correct-horse-battery-staple",
        },
    )
    assert response.status_code == 201
    return response.json()["access_token"]


def test_register_login_and_read_current_identity(
    client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    test_client, _ = client
    register(test_client, "Admin@Example.com")

    login_response = test_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
    )

    assert login_response.status_code == 200
    assert login_response.json()["token_type"] == "bearer"
    assert login_response.json()["expires_in"] == 1800

    me_response = test_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login_response.json()['access_token']}"},
    )

    assert me_response.status_code == 200
    assert me_response.json()["email"] == "admin@example.com"
    assert me_response.json()["tenant_name"] == "Example Store"
    assert me_response.json()["role"] == "merchant_admin"


def test_registration_conflicts_are_rejected(
    client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    test_client, session_factory = client
    register(test_client)

    duplicate_email = test_client.post(
        "/api/v1/auth/register-tenant-admin",
        json={
            "tenant_name": "Second Store",
            "tenant_slug": "second-store",
            "email": "ADMIN@example.com",
            "password": "correct-horse-battery-staple",
        },
    )
    duplicate_slug = test_client.post(
        "/api/v1/auth/register-tenant-admin",
        json={
            "tenant_name": "Third Store",
            "tenant_slug": "example-store",
            "email": "other@example.com",
            "password": "correct-horse-battery-staple",
        },
    )

    assert duplicate_email.status_code == 409
    assert duplicate_slug.status_code == 409

    async def assert_no_partial_registration() -> None:
        async with session_factory() as session:
            users = (await session.execute(select(User))).scalars().all()
            tenants = (await session.execute(select(Tenant))).scalars().all()
            assert [user.email for user in users] == ["admin@example.com"]
            assert [tenant.slug for tenant in tenants] == ["example-store"]

    asyncio.run(assert_no_partial_registration())


def test_invalid_password_and_tokens_are_rejected(
    client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    test_client, _ = client
    register(test_client)

    wrong_password = test_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "wrong-password"},
    )
    malformed_token = test_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not-a-token"},
    )
    expired_token = jwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000000",
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        },
        get_settings().jwt_secret,
        algorithm=get_settings().jwt_algorithm,
    )
    expired_response = test_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert wrong_password.status_code == 401
    assert malformed_token.status_code == 401
    assert expired_response.status_code == 401


def test_production_rejects_the_development_jwt_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production")


@pytest.mark.parametrize("target", ["user", "membership", "tenant"])
def test_disabled_identity_invalidates_existing_token(
    client: tuple[TestClient, async_sessionmaker[AsyncSession]],
    target: str,
) -> None:
    test_client, session_factory = client
    token = register(test_client)

    async def disable_identity() -> None:
        async with session_factory() as session:
            user_statement = select(User).where(User.email == "admin@example.com")
            user = (await session.execute(user_statement)).scalar_one()
            if target == "user":
                user.is_active = False
            elif target == "membership":
                membership = (
                    await session.execute(
                        select(TenantMembership).where(TenantMembership.user_id == user.id)
                    )
                ).scalar_one()
                membership.is_active = False
            else:
                tenant = (await session.execute(select(Tenant))).scalar_one()
                tenant.is_active = False
            await session.commit()

    asyncio.run(disable_identity())
    response = test_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
