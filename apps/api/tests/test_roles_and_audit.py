"""Minimal role, tenant, ownership and metadata-only audit acceptance checks."""

import asyncio

from sqlalchemy import select
from test_conversations import bearer, login, register_tenant_admin
from test_conversations import client as client

from aftercare_api.identity.models import Tenant, TenantMembership, User
from aftercare_api.identity.security import hash_password


def add_role(factory, slug, role, email):
    async def create():
        async with factory() as session, session.begin():
            tenant = await session.scalar(select(Tenant).where(Tenant.slug == slug))
            user = User(email=email, password_hash=hash_password("correct-horse-battery-staple"))
            session.add(user)
            await session.flush()
            session.add(TenantMembership(tenant_id=tenant.id, user_id=user.id, role=role))

    asyncio.run(create())


def test_role_matrix_tenant_scope_and_unchanged_conversation_ownership(client):
    api, factory = client
    admin = bearer(register_tenant_admin(api, "roles", "admin@example.com"))
    tokens = {"merchant_admin": admin}
    for role in ("support_agent", "customer"):
        email = f"{role}@example.com"
        add_role(factory, "roles", role, email)
        tokens[role] = bearer(login(api, email))
    conversation = api.post("/api/v1/conversations", headers=tokens["customer"]).json()
    for role, headers in tokens.items():
        assert api.get("/api/v1/auth/me", headers=headers).json()["role"] == role
        assert api.post("/api/v1/conversations", headers=headers).status_code == 201
        response = api.get("/api/v1/audit-events", headers=headers)
        assert response.status_code == (200 if role == "merchant_admin" else 403)
    for role in ("merchant_admin", "support_agent"):
        assert (
            api.get(f"/api/v1/conversations/{conversation['id']}", headers=tokens[role]).status_code
            == 404
        )
    events = api.get("/api/v1/audit-events", headers=admin).json()
    assert any(event["action"] == "audit.list" and event["result"] == "denied" for event in events)
    other_admin = bearer(register_tenant_admin(api, "other", "other@example.com"))
    own_tenant = api.get("/api/v1/auth/me", headers=other_admin).json()["tenant_id"]
    other_events = api.get(
        "/api/v1/audit-events?tenant_id=" + events[0]["tenant_id"], headers=other_admin
    ).json()
    assert other_events and all(event["tenant_id"] == own_tenant for event in other_events)
    assert api.get("/api/v1/audit-events").status_code == 401


def test_audit_redaction_one_event_per_stream_and_live_role_change(client):
    api, factory = client
    token = register_tenant_admin(api, "redaction", "admin@example.com")
    headers = bearer(token)
    conversation = api.post("/api/v1/conversations", headers=headers).json()
    path = f"/api/v1/conversations/{conversation['id']}"
    private_message = "Private message Order 42 never copy into audit"
    streamed = api.post(
        path + "/messages/stream", headers=headers, json={"content": private_message}
    )
    assert "event: completed" in streamed.text and streamed.text.count("event: delta") > 1
    reply = api.get(path, headers=headers).json()["messages"][-1]
    private_feedback = "Private feedback never copy into audit"
    assert (
        api.post(
            path + f"/messages/{reply['id']}/feedback",
            headers=headers,
            json={"rating": "dislike", "reason": "incorrect", "detail": private_feedback},
        ).status_code
        == 200
    )
    response = api.get("/api/v1/audit-events", headers=headers)
    events = response.json()
    streams = [event for event in events if event["action"] == "message.stream"]
    assert len(streams) == 1
    assert streams[0]["result"] == "accepted" and streams[0]["status_code"] == 200
    assert streams[0]["resource_id"] == conversation["id"]
    assert any(
        event["resource_id"] == reply["id"] and event["action"] == "feedback.save"
        for event in events
    )
    for secret in (private_message, private_feedback, token, "correct-horse-battery-staple"):
        assert secret not in response.text
    assert all(
        set(event)
        == {
            "id",
            "tenant_id",
            "actor_user_id",
            "actor_role",
            "action",
            "resource_type",
            "resource_id",
            "status_code",
            "result",
            "created_at",
        }
        for event in events
    )

    async def change_role():
        async with factory() as session, session.begin():
            membership = await session.scalar(select(TenantMembership))
            membership.role = "customer"

    asyncio.run(change_role())
    assert api.get("/api/v1/audit-events", headers=headers).status_code == 403
    assert api.get(path, headers=headers).status_code == 200
