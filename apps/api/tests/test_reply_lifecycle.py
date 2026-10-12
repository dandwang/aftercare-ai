import asyncio
from uuid import uuid4

import anyio
import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import ClientDisconnect

from aftercare_api.conversations.models import Conversation, Message
from aftercare_api.conversations.router import (
    ReplyStreamingResponse,
    cleanup_reply,
    reply_event_stream,
)
from aftercare_api.conversations.service import (
    ReplyAlreadyGeneratingError,
    cancel_reply,
    create_regenerated_reply,
    create_streaming_reply,
    stream_reply_chunks,
)
from aftercare_api.db.base import Base
from aftercare_api.identity.models import Tenant, TenantMembership, User  # noqa: F401
from aftercare_api.identity.service import CurrentIdentity


class ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


@pytest_asyncio.fixture
async def reply_setup(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'lifecycle.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    identity = CurrentIdentity(uuid4(), "probe@example.test", uuid4(), "Probe", "customer")
    async with factory() as session:
        conversation = Conversation(tenant_id=identity.tenant_id, owner_user_id=identity.user_id)
        session.add(conversation)
        await session.commit()
        _, reply = await create_streaming_reply(session, conversation.id, "Hello", identity)
        reply_id = reply.id
    yield factory, reply_id
    await engine.dispose()


@pytest.mark.asyncio
async def test_stop_after_last_delta_cannot_be_overwritten_by_completion(reply_setup):
    factory, reply_id = reply_setup
    async with factory() as streaming, factory() as stopping:
        reply = await streaming.get(Message, reply_id)
        chunks = stream_reply_chunks(streaming, reply, "Hello")
        deltas = [await anext(chunks) for _ in range(3)]
        stopped = await stopping.get(Message, reply_id)
        await cancel_reply(stopping, stopped)
        with pytest.raises(StopAsyncIteration):
            await anext(chunks)
        await streaming.refresh(reply)
        assert reply.generation_status == "cancelled"
        assert reply.is_current is False
        assert "".join(deltas) == reply.content


@pytest.mark.asyncio
async def test_stale_stop_does_not_cancel_completed_reply(reply_setup):
    factory, reply_id = reply_setup
    async with factory() as streaming, factory() as stopping:
        reply = await streaming.get(Message, reply_id)
        stale = await stopping.get(Message, reply_id)
        async for _ in stream_reply_chunks(streaming, reply, "Hello"):
            pass
        await cancel_reply(stopping, stale)
        await streaming.refresh(reply)
        assert reply.generation_status == "completed"
        assert reply.is_current is True


@pytest.mark.asyncio
async def test_closing_after_started_cancels_persisted_reply(reply_setup):
    factory, reply_id = reply_setup
    async with factory() as session:
        reply = await session.get(Message, reply_id)
        events = reply_event_stream(ConnectedRequest(), session, reply, "Hello")
        assert "event: started" in await anext(events)
        await events.aclose()
    async with factory() as session:
        reply = await session.get(Message, reply_id)
        assert reply.generation_status == "cancelled"
        assert reply.is_current is False


@pytest.mark.asyncio
async def test_task_cancellation_preserves_partial_content(reply_setup):
    factory, reply_id = reply_setup
    first_delta = asyncio.Event()

    async def consume():
        async with factory() as session:
            reply = await session.get(Message, reply_id)
            async for frame in reply_event_stream(ConnectedRequest(), session, reply, "Hello"):
                if "event: delta" in frame:
                    first_delta.set()

    task = asyncio.create_task(consume())
    await first_delta.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with factory() as session:
        reply = await session.get(Message, reply_id)
        assert reply.generation_status == "cancelled"
        assert reply.content == "Placeholder"
        assert reply.is_current is False


@pytest.mark.asyncio
async def test_level_cancellation_uses_fresh_shielded_cleanup(reply_setup):
    factory, reply_id = reply_setup
    async with factory() as session:
        reply = await session.get(Message, reply_id)
        events = reply_event_stream(ConnectedRequest(), session, reply, "Hello")
        with anyio.CancelScope() as scope:
            await anext(events)
            await anext(events)
            scope.cancel()
            await anext(events)
    async with factory() as session:
        reply = await session.get(Message, reply_id)
        assert reply.generation_status == "cancelled"
        assert reply.content == "Placeholder"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_on_body", [False, True])
async def test_asgi_send_failure_cleans_up_even_before_iterator_starts(
    reply_setup, failure_on_body
):
    factory, reply_id = reply_setup

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == ("http.response.body" if failure_on_body else "http.response.start"):
            raise OSError("Disconnected")

    async with factory() as session:
        reply = await session.get(Message, reply_id)
        response = ReplyStreamingResponse(ConnectedRequest(), session, reply, "Hello")
        with pytest.raises(ClientDisconnect):
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
    async with factory() as session:
        reply = await session.get(Message, reply_id)
        assert reply.generation_status == "cancelled"


@pytest.mark.asyncio
async def test_regeneration_conflict_and_cancellation_keep_original_current(reply_setup):
    factory, reply_id = reply_setup
    async with factory() as session:
        reply = await session.get(Message, reply_id)
        async for _ in stream_reply_chunks(session, reply, "Hello"):
            pass
        conversation = await session.get(Conversation, reply.conversation_id)
        conversation_id = conversation.id
        identity = CurrentIdentity(
            conversation.owner_user_id,
            "probe@example.test",
            conversation.tenant_id,
            "Probe",
            "customer",
        )
        _, regenerated = await create_regenerated_reply(
            session, conversation.id, reply_id, identity
        )
        with pytest.raises(ReplyAlreadyGeneratingError):
            await create_regenerated_reply(session, conversation.id, reply_id, identity)
        await session.refresh(regenerated)
        await cancel_reply(session, regenerated)
        await cancel_reply(session, regenerated)
        await session.refresh(reply)
        assert reply.is_current is True
        _, next_reply = await create_regenerated_reply(session, conversation_id, reply_id, identity)
        assert next_reply.reply_version == 3
        assert next_reply.is_current is False


@pytest.mark.asyncio
@pytest.mark.parametrize("violation", ["version", "current", "running", "unfinished_current"])
async def test_database_rejects_reply_invariant_violations(reply_setup, violation):
    factory, reply_id = reply_setup
    async with factory() as session:
        reply = await session.get(Message, reply_id)
        if violation in ("version", "current"):
            async for _ in stream_reply_chunks(session, reply, "Hello"):
                pass
        invalid = Message(
            conversation_id=reply.conversation_id,
            tenant_id=reply.tenant_id,
            role="assistant",
            content="Invalid",
            in_reply_to_message_id=reply.in_reply_to_message_id,
            reply_version=1 if violation == "version" else 2,
            generation_status="completed" if violation in ("version", "current") else "generating",
            is_current=violation in ("current", "unfinished_current"),
        )
        session.add(invalid)
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_cleanup_rolls_back_broken_transaction_before_cancelling(reply_setup):
    factory, reply_id = reply_setup
    async with factory() as session:
        reply = await session.get(Message, reply_id)
        session.add(
            Message(
                conversation_id=reply.conversation_id,
                tenant_id=reply.tenant_id,
                role="assistant",
                content="Invalid",
                in_reply_to_message_id=reply.in_reply_to_message_id,
                reply_version=1,
                generation_status="generating",
                is_current=False,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await cleanup_reply(session, reply_id)
    async with factory() as session:
        reply = await session.get(Message, reply_id)
        assert reply.generation_status == "cancelled"
