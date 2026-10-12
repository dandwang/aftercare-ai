"""Run only against an explicitly supplied disposable PostgreSQL test database."""

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aftercare_api.conversations.models import Message
from aftercare_api.conversations.service import (
    ReplyAlreadyGeneratingError,
    add_message_pair,
    cancel_reply,
    create_conversation,
    create_regenerated_reply,
    create_streaming_reply,
    stream_reply_chunks,
)
from aftercare_api.identity.models import Tenant, User
from aftercare_api.identity.service import CurrentIdentity

TEST_URL = os.environ.get("AFTERCARE_TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not TEST_URL, reason="PostgreSQL URL required"),
]
API_ROOT = Path(__file__).resolve().parents[1]


async def migrate(target, downgrade=False, expect_success=True):
    environment = {**os.environ, "AFTERCARE_DATABASE_URL": TEST_URL}
    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", "downgrade" if downgrade else "upgrade", target],
        cwd=API_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if expect_success:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
    return result


class ObservedSession(AsyncSession):
    async def execute(self, statement, *args, **kwargs):
        if getattr(statement, "_for_update_arg", None) is not None and "locking" in self.info:
            self.info["locking"].set()
        return await super().execute(statement, *args, **kwargs)


@pytest_asyncio.fixture
async def postgres(request):
    assert make_url(TEST_URL).database.endswith("_test"), "Refuse non-test database"
    await migrate("base", downgrade=True)
    await migrate(getattr(request, "param", "head"))
    engine = create_async_engine(TEST_URL)
    factory = async_sessionmaker(engine, class_=ObservedSession, expire_on_commit=False)
    yield engine, factory
    await engine.dispose()


async def seed_identity(factory):
    async with factory() as session:
        tenant = Tenant(name="Probe", slug=f"probe-{uuid4()}")
        user = User(email=f"{uuid4()}@example.test", password_hash="unused-test-hash")
        session.add_all([tenant, user])
        await session.commit()
        return CurrentIdentity(user.id, user.email, tenant.id, tenant.name, "customer")


async def seeded_reply(factory, streaming=False):
    identity = await seed_identity(factory)
    async with factory() as session:
        conversation = await create_conversation(session, identity)
        if streaming:
            _, reply = await create_streaming_reply(session, conversation.id, "Hello", identity)
        else:
            _, messages = await add_message_pair(session, conversation.id, "Hello", identity)
            reply = messages[-1]
        return identity, conversation.id, reply.id


async def test_concurrent_regeneration_serializes_on_source_row(postgres):
    _, factory = postgres
    identity, conversation_id, reply_id = await seeded_reply(factory)
    events = [asyncio.Event(), asyncio.Event()]

    async def regenerate(event):
        async with factory(info={"locking": event}) as session:
            try:
                _, reply = await create_regenerated_reply(
                    session, conversation_id, reply_id, identity
                )
                return reply.id
            except ReplyAlreadyGeneratingError:
                return None

    async with factory() as holder:
        reply = await holder.get(Message, reply_id)
        await holder.execute(
            select(Message.id).where(Message.id == reply.in_reply_to_message_id).with_for_update()
        )
        tasks = [asyncio.create_task(regenerate(event)) for event in events]
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in events)), 5)
        assert not any(task.done() for task in tasks)
        await holder.commit()
    results = await asyncio.wait_for(asyncio.gather(*tasks), 5)
    assert results.count(None) == 1
    new_id = next(result for result in results if result is not None)
    async with factory() as session:
        new_reply = await session.get(Message, new_id)
        original = await session.get(Message, reply_id)
        assert new_reply.reply_version == 2
        assert not new_reply.is_current and original.is_current
        await cancel_reply(session, new_reply)
        _, third = await create_regenerated_reply(session, conversation_id, reply_id, identity)
        assert third.reply_version == 3
        async for _ in stream_reply_chunks(session, third, "Hello"):
            pass
        await session.refresh(original)
        assert third.is_current and not original.is_current


@pytest.mark.parametrize("stop_first", [True, False])
async def test_stop_completion_race_on_independent_connections(postgres, stop_first):
    _, factory = postgres
    _, _, reply_id = await seeded_reply(factory, streaming=True)
    async with factory() as streaming, factory() as stopping:
        assert await streaming.scalar(text("SELECT pg_backend_pid()")) != await stopping.scalar(
            text("SELECT pg_backend_pid()")
        )
        reply = await streaming.get(Message, reply_id)
        stale = await stopping.get(Message, reply_id)
        chunks = stream_reply_chunks(streaming, reply, "Hello")
        deltas = [await anext(chunks) for _ in range(3)]
        if stop_first:
            await cancel_reply(stopping, stale)
        with pytest.raises(StopAsyncIteration):
            await anext(chunks)
        if not stop_first:
            await cancel_reply(stopping, stale)
        await streaming.refresh(reply)
        assert reply.generation_status == ("cancelled" if stop_first else "completed")
        assert reply.is_current is (not stop_first)
        assert "".join(deltas) == reply.content


@pytest.mark.parametrize("violation", ["version", "current", "running", "unfinished_current"])
async def test_postgres_enforces_unique_versions_and_current(postgres, violation):
    _, factory = postgres
    _, _, reply_id = await seeded_reply(
        factory, streaming=violation in ("running", "unfinished_current")
    )
    async with factory() as session:
        reply = await session.get(Message, reply_id)
        session.add(
            Message(
                conversation_id=reply.conversation_id,
                tenant_id=reply.tenant_id,
                role="assistant",
                content="Invalid",
                in_reply_to_message_id=reply.in_reply_to_message_id,
                reply_version=1 if violation == "version" else 2,
                generation_status="generating"
                if violation in ("running", "unfinished_current")
                else "completed",
                is_current=violation in ("current", "unfinished_current"),
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def historical_messages(factory, scenario):
    identity = await seed_identity(factory)
    conversation_id = uuid4()
    origin = datetime(2026, 9, 23, tzinfo=UTC)
    user_id, second_user_id = uuid4(), uuid4()
    rows = [(user_id, "user", "First", origin)]
    if scenario == "wrong_nearest":
        rows += [(second_user_id, "user", "Second", origin + timedelta(seconds=1))]
    if scenario == "ambiguous":
        rows += [(second_user_id, "user", "First", origin)]
    if scenario == "orphan":
        rows = []
    rows += [(uuid4(), "assistant", "Placeholder reply: First", origin + timedelta(seconds=2))]
    if scenario == "duplicate":
        rows += [(uuid4(), "assistant", "Placeholder reply: First", origin + timedelta(seconds=3))]
    async with factory() as session:
        await session.execute(
            text("""
            INSERT INTO conversations (id, tenant_id, owner_user_id)
            VALUES (:id, :tenant, :owner)
        """),
            {"id": conversation_id, "tenant": identity.tenant_id, "owner": identity.user_id},
        )
        for message_id, role, content, created_at in rows:
            await session.execute(
                text("""
                INSERT INTO messages (id, conversation_id, tenant_id, role, content, created_at)
                VALUES (:id, :conversation, :tenant, :role, :content, :created_at)
            """),
                {
                    "id": message_id,
                    "conversation": conversation_id,
                    "tenant": identity.tenant_id,
                    "role": role,
                    "content": content,
                    "created_at": created_at,
                },
            )
        await session.commit()
    return user_id, rows


@pytest.mark.parametrize("postgres", ["20260923_02"], indirect=True)
@pytest.mark.parametrize("scenario", ["normal", "wrong_nearest", "duplicate"])
async def test_history_backfill_and_upgrade_downgrade_upgrade(postgres, scenario):
    _, factory = postgres
    user_id, original = await historical_messages(factory, scenario)
    await migrate("head")
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    text("""
            SELECT id, role, content, in_reply_to_message_id, reply_version, is_current
            FROM messages ORDER BY created_at, id
        """)
                )
            )
            .mappings()
            .all()
        )
        assert [(row["id"], row["role"], row["content"]) for row in rows] == [
            (row[0], row[1], row[2]) for row in original
        ]
        replies = [row for row in rows if row["role"] == "assistant"]
        assert all(row["in_reply_to_message_id"] == user_id for row in replies)
        assert [row["reply_version"] for row in replies] == list(range(1, len(replies) + 1))
        assert [row["is_current"] for row in replies] == [False] * (len(replies) - 1) + [True]
    await migrate("20260923_02", downgrade=True)
    await migrate("head")
    async with factory() as session:
        assert await session.scalar(text("SELECT COUNT(*) FROM messages")) == len(original)
        assert (
            await session.scalar(text("SELECT version_num FROM alembic_version")) == "20261012_05"
        )


@pytest.mark.parametrize("postgres", ["20260923_02"], indirect=True)
@pytest.mark.parametrize("scenario", ["orphan", "ambiguous"])
async def test_ambiguous_history_fails_and_rolls_back(postgres, scenario):
    _, factory = postgres
    _, original = await historical_messages(factory, scenario)
    result = await migrate("head", expect_success=False)
    assert "Ambiguous or unpaired placeholder history" in result.stderr
    async with factory() as session:
        assert (
            await session.scalar(text("SELECT version_num FROM alembic_version")) == "20260923_02"
        )
        assert await session.scalar(text("SELECT COUNT(*) FROM messages")) == len(original)
        columns = (
            (
                await session.execute(
                    text("""
            SELECT column_name FROM information_schema.columns WHERE table_name = 'messages'
        """)
                )
            )
            .scalars()
            .all()
        )
        assert "reply_version" not in columns


@pytest.mark.parametrize("postgres", ["20260923_03"], indirect=True)
async def test_existing_version_numbers_and_cancelled_history_are_preserved(postgres):
    _, factory = postgres
    _, _ = await historical_messages(factory, "duplicate")
    async with factory() as session:
        await session.execute(
            text("""
            UPDATE messages reply SET in_reply_to_message_id = source.id, reply_version = 1
            FROM messages source WHERE reply.role = 'assistant' AND source.role = 'user'
        """)
        )
        await session.execute(
            text("""
            UPDATE messages SET reply_version = 3, generation_status = 'cancelled'
            WHERE id = (SELECT id FROM messages WHERE role = 'assistant'
                        ORDER BY created_at DESC LIMIT 1)
        """)
        )
        await session.commit()
    await migrate("head")
    await migrate("20260923_03", downgrade=True)
    await migrate("head")
    async with factory() as session:
        replies = (
            (
                await session.execute(
                    select(Message).where(Message.role == "assistant").order_by(Message.created_at)
                )
            )
            .scalars()
            .all()
        )
        assert [reply.reply_version for reply in replies] == [1, 3]
        assert [reply.generation_status for reply in replies] == ["completed", "cancelled"]
        assert [reply.is_current for reply in replies] == [True, False]


@pytest.mark.parametrize("postgres", ["20260923_03"], indirect=True)
@pytest.mark.parametrize(
    "corruption, expected",
    [
        ("version", "Conflicting existing version numbers"),
        ("running", "Multiple running replies"),
        ("same_time", "Ambiguous reply version order"),
        ("cross_conversation", "Invalid reply lineage"),
    ],
)
async def test_corrupt_existing_lineage_is_rejected_atomically(postgres, corruption, expected):
    _, factory = postgres
    _, _ = await historical_messages(factory, "duplicate")
    async with factory() as session:
        await session.execute(
            text("""
            UPDATE messages reply SET in_reply_to_message_id = source.id, reply_version = 1
            FROM messages source WHERE reply.role = 'assistant' AND source.role = 'user'
        """)
        )
        if corruption == "version":
            await session.execute(
                text("UPDATE messages SET reply_version = 2 WHERE role = 'assistant'")
            )
        elif corruption == "running":
            await session.execute(
                text(
                    "UPDATE messages SET generation_status = 'generating' WHERE role = 'assistant'"
                )
            )
        elif corruption == "same_time":
            await session.execute(
                text(
                    "UPDATE messages SET created_at = '2026-09-23T00:00:02Z' "
                    "WHERE role = 'assistant'"
                )
            )
        else:
            other_id = uuid4()
            await session.execute(
                text("""
                INSERT INTO conversations (id, tenant_id, owner_user_id)
                SELECT :id, tenant_id, owner_user_id FROM conversations LIMIT 1
            """),
                {"id": other_id},
            )
            await session.execute(
                text("""
                UPDATE messages SET conversation_id = :id,
                  reply_version = EXTRACT(SECOND FROM created_at)::int WHERE role = 'assistant'
            """),
                {"id": other_id},
            )
        await session.commit()
    result = await migrate("head", expect_success=False)
    assert expected in result.stderr
    async with factory() as session:
        assert (
            await session.scalar(text("SELECT version_num FROM alembic_version")) == "20260923_03"
        )
        assert await session.scalar(text("SELECT COUNT(*) FROM messages")) == 3
