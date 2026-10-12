"""Exercise real sockets against the disposable M2-D Compose project."""

import asyncio
import json
import os
import time
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

API_URL = os.environ.get("AFTERCARE_TEST_API_URL")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not API_URL, reason="Disposable API URL required"),
]


@pytest_asyncio.fixture
async def http_client():
    assert API_URL == "http://127.0.0.1:18000", "Refuse non-disposable API endpoint"
    async with httpx.AsyncClient(base_url=API_URL, timeout=10) as client:
        slug = f"http-{uuid4()}"
        registered = await client.post(
            "/api/v1/auth/register-tenant-admin",
            json={
                "tenant_name": "HTTP Probe",
                "tenant_slug": slug,
                "email": f"{slug}@example.test",
                "password": "disposable-test-password",
            },
        )
        assert registered.status_code == 201
        client.headers["Authorization"] = f"Bearer {registered.json()['access_token']}"
        conversation = await client.post("/api/v1/conversations")
        assert conversation.status_code == 201
        yield client, f"/api/v1/conversations/{conversation.json()['id']}"


async def next_event(lines):
    event = None
    async for line in lines:
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            return event, json.loads(line[6:])
    raise AssertionError("EOF before expected event")


async def wait_for_cancelled(client, path, reply_id):
    for _ in range(100):
        history = (await client.get(path)).json()["messages"]
        reply = next(message for message in history if message["id"] == reply_id)
        if reply["generation_status"] == "cancelled":
            return reply
        await asyncio.sleep(0.02)
    raise AssertionError("Disconnected reply remained generating")


async def test_socket_stream_completes_in_chunks_and_regenerates(http_client):
    client, path = http_client
    started_at = time.monotonic()
    deltas = []
    async with client.stream(
        "POST", f"{path}/messages/stream", json={"content": "Where is order 42?"}
    ) as response:
        assert response.status_code == 200
        lines = response.aiter_lines()
        event, started = await next_event(lines)
        assert event == "started"
        assert started["message"]["generation_status"] == "generating"
        assert not started["message"]["is_current"]
        while True:
            event, payload = await next_event(lines)
            if event == "delta":
                deltas.append(payload["content"])
            else:
                assert event == "completed"
                completed = payload["message"]
                break
    assert time.monotonic() - started_at >= 0.1
    assert len(deltas) > 1
    assert "".join(deltas) == completed["content"] == "Placeholder reply: Where is order 42?"
    regenerated = await client.post(f"{path}/messages/{completed['id']}/regenerate/stream")
    assert regenerated.status_code == 200 and "event: completed" in regenerated.text
    replies = [
        message
        for message in (await client.get(path)).json()["messages"]
        if message["role"] == "assistant"
    ]
    assert [message["reply_version"] for message in replies] == [1, 2]
    assert [message["is_current"] for message in replies] == [False, True]


async def test_socket_stop_preserves_cancelled_terminal_and_content(http_client):
    client, path = http_client
    async with client.stream(
        "POST", f"{path}/messages/stream", json={"content": " ".join(["word"] * 30)}
    ) as response:
        lines = response.aiter_lines()
        _, started = await next_event(lines)
        assert (await next_event(lines))[0] == "delta"
        reply_id = started["message"]["id"]
        stopped = await client.post(f"{path}/messages/{reply_id}/stop")
        assert stopped.json()["generation_status"] == "cancelled"
        while True:
            event, payload = await next_event(lines)
            if event != "delta":
                assert event == "cancelled"
                assert payload["message"]["content"] == stopped.json()["content"]
                break
    persisted = await wait_for_cancelled(client, path, reply_id)
    assert persisted["content"] == stopped.json()["content"]
    assert not persisted["is_current"]


@pytest.mark.parametrize("read_delta", [False, True])
async def test_socket_disconnect_cancels_without_explicit_stop(http_client, read_delta):
    client, path = http_client
    async with client.stream(
        "POST", f"{path}/messages/stream", json={"content": " ".join(["word"] * 30)}
    ) as response:
        lines = response.aiter_lines()
        _, started = await next_event(lines)
        if read_delta:
            assert (await next_event(lines))[0] == "delta"
        reply_id = started["message"]["id"]
    reply = await wait_for_cancelled(client, path, reply_id)
    assert bool(reply["content"]) is read_delta
    assert not reply["is_current"]


async def test_socket_concurrent_regeneration_returns_conflict_and_keeps_history(http_client):
    client, path = http_client
    history = (
        await client.post(f"{path}/messages", json={"content": " ".join(["word"] * 30)})
    ).json()
    original = history["messages"][-1]
    endpoint = f"{path}/messages/{original['id']}/regenerate/stream"
    async with client.stream("POST", endpoint) as response:
        lines = response.aiter_lines()
        _, started = await next_event(lines)
        conflict = await client.post(endpoint)
        assert conflict.status_code == 409
    cancelled = await wait_for_cancelled(client, path, started["message"]["id"])
    assert cancelled["reply_version"] == 2
    history = (await client.get(path)).json()["messages"]
    assert next(message for message in history if message["id"] == original["id"])["is_current"]
    regenerated = await client.post(endpoint)
    assert regenerated.status_code == 200 and "event: completed" in regenerated.text
    replies = [
        message
        for message in (await client.get(path)).json()["messages"]
        if message["role"] == "assistant"
    ]
    assert [message["reply_version"] for message in replies] == [1, 2, 3]
    assert [message["is_current"] for message in replies] == [False, False, True]
