"""Normal M2-E learning flows: bounded history, fact recall and version feedback."""

import asyncio
import json
from uuid import UUID, uuid4

from test_conversations import bearer, register_tenant_admin
from test_conversations import client as client

from aftercare_api.config import Settings
from aftercare_api.conversations.context import prepare_context
from aftercare_api.conversations.models import Conversation, GenerationContext
from aftercare_api.conversations.token_budget import get_token_meter


def conversation_setup(test_client):
    token = register_tenant_admin(test_client, f"context-{uuid4()}", f"{uuid4()}@example.test")
    headers = bearer(token)
    created = test_client.post("/api/v1/conversations", headers=headers)
    return f"/api/v1/conversations/{created.json()['id']}", headers


def send(test_client, path, headers, content):
    response = test_client.post(f"{path}/messages", headers=headers, json={"content": content})
    assert response.status_code == 200, response.text
    return response.json()


def test_long_conversation_recalls_fact_from_budgeted_summary(client, monkeypatch):
    test_client, factory = client
    settings = Settings(context_max_turns=2, context_token_budget=2048, output_token_limit=128)
    monkeypatch.setattr("aftercare_api.conversations.context.get_settings", lambda: settings)
    path, headers = conversation_setup(test_client)
    first = send(test_client, path, headers, "My order number is 42; 商品：红色鞋，数量：2")
    source_id = first["messages"][0]["id"]
    for index in range(8):
        send(test_client, path, headers, f"Topic {index}: " + "packaging " * 300)
    response = test_client.post(
        f"{path}/messages/stream", headers=headers, json={"content": "我刚才问的是哪一笔订单？"}
    )
    assert response.status_code == 200 and "event: completed" in response.text
    history = test_client.get(path, headers=headers).json()
    reply = history["messages"][-1]
    assert reply["content"] == "Context reply (user-reported): order 42."
    snapshot = next(
        context for context in history["contexts"] if context["message_id"] == reply["id"]
    )
    assert snapshot["summary"] is not None
    assert any(
        fact["kind"] == "order" and fact["value"] == "42" and fact["source_message_id"] == source_id
        for fact in snapshot["summary"]["facts"]
    )
    assert snapshot["input_token_count"] + snapshot["output_token_limit"] <= 2048

    async def verify_actual_prompt():
        async with factory() as session:
            saved = await session.get(GenerationContext, UUID(reply["id"]))
            meter = get_token_meter(saved.tokenizer_name)
            assert (
                meter.count(" ".join(message["content"] for message in history["messages"]))
                > settings.context_token_budget
            )
            assert meter.count(saved.prompt) == saved.input_token_count
            assert len(json.loads(saved.prompt)["turns"]) <= 2
            assert meter.count(reply["content"]) <= saved.output_token_limit

    asyncio.run(verify_actual_prompt())


def test_current_version_is_selected_and_old_input_regeneration_has_no_future_turns(client):
    test_client, factory = client
    path, headers = conversation_setup(test_client)
    first = send(test_client, path, headers, "Order 42")
    original = first["messages"][-1]
    send(test_client, path, headers, "Future topic about another product")
    regenerated = test_client.post(
        f"{path}/messages/{original['id']}/regenerate/stream",
        headers=headers,
    )
    assert regenerated.status_code == 200
    history = test_client.get(path, headers=headers).json()
    new_reply = next(
        message
        for message in history["messages"]
        if message["role"] == "assistant" and message["reply_version"] == 2
    )
    snapshot = next(
        context for context in history["contexts"] if context["message_id"] == new_reply["id"]
    )
    assert snapshot["selected_message_ids"] == [first["messages"][0]["id"]]
    latest = send(test_client, path, headers, "Which order did I mention?")
    latest_context = latest["contexts"][-1]
    assert new_reply["id"] in latest_context["selected_message_ids"]
    assert original["id"] not in latest_context["selected_message_ids"]

    async def verify_summary_versions():
        async with factory() as session:
            conversation = await session.get(Conversation, UUID(first["id"]))
            context = await prepare_context(
                session,
                conversation,
                "Next topic",
                uuid4(),
                settings=Settings(context_max_turns=0),
            )
            assert new_reply["id"] in context.summary.covered_message_ids
            assert original["id"] not in context.summary.covered_message_ids

    asyncio.run(verify_summary_versions())


def test_feedback_updates_and_stays_with_its_original_reply_after_regeneration(client):
    test_client, _ = client
    path, headers = conversation_setup(test_client)
    history = send(test_client, path, headers, "Order 42")
    reply = history["messages"][-1]
    endpoint = f"{path}/messages/{reply['id']}/feedback"
    liked = test_client.post(endpoint, headers=headers, json={"rating": "like"})
    assert liked.status_code == 200
    disliked = test_client.post(
        endpoint,
        headers=headers,
        json={
            "rating": "dislike",
            "reason": "unclear",
            "detail": "Please explain the next step.",
        },
    )
    assert disliked.status_code == 200 and disliked.json()["id"] == liked.json()["id"]
    assert (
        test_client.post(
            f"{path}/messages/{reply['id']}/regenerate/stream", headers=headers
        ).status_code
        == 200
    )
    reloaded = test_client.get(path, headers=headers).json()
    assert len(reloaded["feedback"]) == 1
    assert reloaded["feedback"][0]["message_id"] == reply["id"]
    assert reloaded["feedback"][0]["detail"] == "Please explain the next step."
    assert not next(message for message in reloaded["messages"] if message["id"] == reply["id"])[
        "is_current"
    ]
    other_token = register_tenant_admin(test_client, f"other-{uuid4()}", f"{uuid4()}@example.test")
    assert (
        test_client.post(endpoint, headers=bearer(other_token), json={"rating": "like"}).status_code
        == 404
    )
