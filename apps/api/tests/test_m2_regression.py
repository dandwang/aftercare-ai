"""Normal M2 chain over real sockets in the disposable three-role demonstration."""

import os

import httpx
import pytest
from test_reply_http import next_event

API_URL = os.environ.get("AFTERCARE_TEST_API_URL")
DEMO_PASSWORD = os.environ.get("AFTERCARE_TEST_DEMO_PASSWORD")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not API_URL or not DEMO_PASSWORD, reason="Disposable seeded demo required"),
]


async def test_three_role_m2_normal_chain():
    assert API_URL == "http://127.0.0.1:18000", "Refuse non-disposable API endpoint"
    async with httpx.AsyncClient(base_url=API_URL, timeout=20) as api:
        headers = {}
        for role, email in {
            "merchant_admin": "admin@demo.example.test",
            "support_agent": "support@demo.example.test",
            "customer": "customer@demo.example.test",
        }.items():
            response = await api.post(
                "/api/v1/auth/login",
                json={
                    "email": email,
                    "password": DEMO_PASSWORD,
                },
            )
            assert response.status_code == 200
            headers[role] = {"Authorization": "Bearer " + response.json()["access_token"]}
            me = await api.get("/api/v1/auth/me", headers=headers[role])
            assert me.json()["role"] == role
            if role == "customer":
                tenant_id = me.json()["tenant_id"]
        customer = headers["customer"]
        created = await api.post("/api/v1/conversations", headers=customer)
        assert created.status_code == 201
        conversation_id = created.json()["id"]
        path = f"/api/v1/conversations/{conversation_id}"
        for content in (
            "Order 42，商品：红色鞋，数量：2。",
            "Packaging guidelines",
            "Shipping options",
            "Return policy overview",
            "我刚才问的是哪一笔订单？",
        ):
            response = await api.post(
                path + "/messages/stream", headers=customer, json={"content": content}
            )
            assert response.status_code == 200 and "event: completed" in response.text
        history = (await api.get(path, headers=customer)).json()
        original = history["messages"][-1]
        assert "order 42" in original["content"]
        context = next(item for item in history["contexts"] if item["message_id"] == original["id"])
        assert (
            context["input_token_count"] + context["output_token_limit"]
            <= context["total_token_budget"]
        )
        assert {fact["kind"] for fact in context["summary"]["facts"]} >= {
            "order",
            "product",
            "quantity",
        }
        feedback_path = path + f"/messages/{original['id']}/feedback"
        assert (
            await api.post(
                feedback_path,
                headers=customer,
                json={
                    "rating": "dislike",
                    "reason": "unclear",
                    "detail": "Demo feedback",
                },
            )
        ).status_code == 200
        regenerated = await api.post(
            path + f"/messages/{original['id']}/regenerate/stream", headers=customer
        )
        assert "event: completed" in regenerated.text
        history = (await api.get(path, headers=customer)).json()
        assert any(
            item["reply_version"] == 2 and item["is_current"] for item in history["messages"]
        )
        assert any(
            item["message_id"] == original["id"] and item["rating"] == "dislike"
            for item in history["feedback"]
        )
        async with api.stream(
            "POST",
            path + "/messages/stream",
            headers=customer,
            json={"content": " ".join(["packaging"] * 100)},
        ) as response:
            lines = response.aiter_lines()
            event, started = await next_event(lines)
            assert event == "started"
            event, _ = await next_event(lines)
            assert event == "delta"
            reply_id = started["message"]["id"]
            stopped = await api.post(path + f"/messages/{reply_id}/stop", headers=customer)
            assert stopped.status_code == 200 and stopped.json()["generation_status"] == "cancelled"
            async for _ in lines:
                pass
        history = (await api.get(path, headers=customer)).json()
        assert (
            next(item for item in history["messages"] if item["id"] == reply_id)[
                "generation_status"
            ]
            == "cancelled"
        )
        for role in ("merchant_admin", "support_agent"):
            assert (await api.get(path, headers=headers[role])).status_code == 404
        for role in ("support_agent", "customer"):
            assert (await api.get("/api/v1/audit-events", headers=headers[role])).status_code == 403
        events = (
            await api.get("/api/v1/audit-events?limit=100", headers=headers["merchant_admin"])
        ).json()
        assert {item["action"] for item in events} >= {
            "auth.login",
            "conversation.create",
            "message.stream",
            "message.stop",
            "message.regenerate",
            "feedback.save",
            "audit.list",
        }
        assert all(item["tenant_id"] == tenant_id for item in events)
        own_streams = [
            item
            for item in events
            if item["action"] == "message.stream" and item["resource_id"] == conversation_id
        ]
        assert len(own_streams) == 6 and all(item["result"] == "accepted" for item in own_streams)
        print(
            f"M2 regression: input={context['input_token_count']}, "
            f"reserved={context['output_token_limit']}, total={context['total_token_budget']}, "
            f"facts={len(context['summary']['facts'])}, streams={len(own_streams)}"
        )
