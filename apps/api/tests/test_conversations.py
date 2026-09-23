import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aftercare_api.conversations.models import Conversation, Message
from aftercare_api.db.base import Base
from aftercare_api.db.session import get_session
from aftercare_api.identity.models import Tenant, TenantMembership, User
from aftercare_api.identity.security import hash_password
from aftercare_api.main import app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[tuple[TestClient, async_sessionmaker[AsyncSession]]]:
    database_path = tmp_path / "conversations.db"
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


def register_tenant_admin(test_client: TestClient, slug: str, email: str) -> str:
    response = test_client.post(
        "/api/v1/auth/register-tenant-admin",
        json={
            "tenant_name": f"{slug} Store",
            "tenant_slug": slug,
            "email": email,
            "password": "correct-horse-battery-staple",
        },
    )
    assert response.status_code == 201
    return response.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def add_customer(
    session_factory: async_sessionmaker[AsyncSession], tenant_slug: str, email: str
) -> str:
    async def create_customer() -> None:
        async with session_factory() as session, session.begin():
            tenant = (
                await session.execute(select(Tenant).where(Tenant.slug == tenant_slug))
            ).scalar_one()
            user = User(email=email, password_hash=hash_password("correct-horse-battery-staple"))
            session.add(user)
            await session.flush()
            session.add(TenantMembership(tenant_id=tenant.id, user_id=user.id, role="customer"))

    asyncio.run(create_customer())
    return email


def login(test_client: TestClient, email: str) -> str:
    response = test_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery-staple"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_create_send_and_reload_persisted_conversation(
    client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    test_client, _ = client
    token = register_tenant_admin(test_client, "example-store", "admin@example.com")

    created = test_client.post("/api/v1/conversations", headers=bearer(token))
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    sent = test_client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=bearer(token),
        json={"content": "Where is my order?"},
    )

    assert sent.status_code == 200
    assert [message["role"] for message in sent.json()["messages"]] == ["user", "assistant"]
    assert sent.json()["messages"][1]["content"] == "Placeholder reply: Where is my order?"

    reloaded = test_client.get(f"/api/v1/conversations/{conversation_id}", headers=bearer(token))
    listed = test_client.get("/api/v1/conversations", headers=bearer(token))

    assert reloaded.status_code == 200
    assert [message["content"] for message in reloaded.json()["messages"]] == [
        "Where is my order?",
        "Placeholder reply: Where is my order?",
    ]
    assert [conversation["id"] for conversation in listed.json()] == [conversation_id]


def test_conversation_owner_and_tenant_isolation(
    client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    test_client, session_factory = client
    owner_token = register_tenant_admin(test_client, "alpha-store", "owner@example.com")
    created = test_client.post("/api/v1/conversations", headers=bearer(owner_token))
    conversation_id = created.json()["id"]
    add_customer(session_factory, "alpha-store", "customer@example.com")
    same_tenant_token = login(test_client, "customer@example.com")
    other_tenant_token = register_tenant_admin(test_client, "beta-store", "other@example.com")

    same_tenant_read = test_client.get(
        f"/api/v1/conversations/{conversation_id}", headers=bearer(same_tenant_token)
    )
    cross_tenant_read = test_client.get(
        f"/api/v1/conversations/{conversation_id}", headers=bearer(other_tenant_token)
    )
    same_tenant_list = test_client.get("/api/v1/conversations", headers=bearer(same_tenant_token))
    cross_tenant_list = test_client.get("/api/v1/conversations", headers=bearer(other_tenant_token))

    assert same_tenant_read.status_code == 404
    assert cross_tenant_read.status_code == 404
    assert same_tenant_list.json() == []
    assert cross_tenant_list.json() == []


def test_blank_message_is_rejected_without_persisting_data(
    client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    test_client, session_factory = client
    token = register_tenant_admin(test_client, "example-store", "admin@example.com")
    created = test_client.post("/api/v1/conversations", headers=bearer(token))
    conversation_id = created.json()["id"]

    response = test_client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=bearer(token),
        json={"content": "   "},
    )

    assert response.status_code == 422

    async def assert_no_messages() -> None:
        async with session_factory() as session:
            assert (await session.execute(select(Message))).scalars().all() == []
            assert len((await session.execute(select(Conversation))).scalars().all()) == 1

    asyncio.run(assert_no_messages())
