"""Business operations for tenant-scoped conversations."""

import asyncio
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aftercare_api.conversations.models import Conversation, Message, utc_now
from aftercare_api.identity.service import CurrentIdentity


class ConversationNotFoundError(Exception):
    """Raised when a conversation is absent or inaccessible to the current identity."""


class MessageNotFoundError(Exception):
    """Raised when a reply is absent or inaccessible through its conversation."""


async def create_conversation(session: AsyncSession, identity: CurrentIdentity) -> Conversation:
    """Create a conversation owned by the current authenticated user."""

    conversation = Conversation(tenant_id=identity.tenant_id, owner_user_id=identity.user_id)
    session.add(conversation)
    await session.commit()
    return conversation


async def list_conversations(
    session: AsyncSession, identity: CurrentIdentity
) -> list[Conversation]:
    """List only conversations that belong to the current tenant and user."""

    statement = (
        select(Conversation)
        .where(
            Conversation.tenant_id == identity.tenant_id,
            Conversation.owner_user_id == identity.user_id,
        )
        .order_by(Conversation.updated_at.desc())
    )
    return list((await session.execute(statement)).scalars())


async def get_conversation(
    session: AsyncSession, conversation_id: UUID, identity: CurrentIdentity
) -> Conversation:
    """Resolve a conversation through trusted tenant and ownership filters."""

    statement = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.tenant_id == identity.tenant_id,
        Conversation.owner_user_id == identity.user_id,
    )
    conversation = (await session.execute(statement)).scalar_one_or_none()
    if conversation is None:
        raise ConversationNotFoundError
    return conversation


async def list_messages(session: AsyncSession, conversation_id: UUID) -> list[Message]:
    """Return messages in stable creation order after ownership has been checked."""

    statement = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at, Message.id)
    )
    return list((await session.execute(statement)).scalars())


async def add_message_pair(
    session: AsyncSession,
    conversation_id: UUID,
    content: str,
    identity: CurrentIdentity,
) -> tuple[Conversation, list[Message]]:
    """Persist a user message and its deterministic placeholder reply atomically."""

    conversation = await get_conversation(session, conversation_id, identity)
    created_at = utc_now()
    user_message = Message(
        conversation_id=conversation.id,
        tenant_id=identity.tenant_id,
        role="user",
        content=content,
        created_at=created_at,
    )
    session.add(user_message)
    await session.flush()
    assistant_message = Message(
        conversation_id=conversation.id,
        tenant_id=identity.tenant_id,
        role="assistant",
        content=f"Placeholder reply: {content}",
        in_reply_to_message_id=user_message.id,
        reply_version=1,
        generation_status="completed",
        is_current=True,
        created_at=created_at + timedelta(microseconds=1),
    )
    conversation.updated_at = assistant_message.created_at
    session.add(assistant_message)
    await session.commit()
    return conversation, [user_message, assistant_message]


async def create_streaming_reply(
    session: AsyncSession,
    conversation_id: UUID,
    content: str,
    identity: CurrentIdentity,
) -> tuple[Conversation, Message]:
    """Persist a user message and an empty, cancellable assistant reply before streaming."""

    conversation = await get_conversation(session, conversation_id, identity)
    created_at = utc_now()
    user_message = Message(
        conversation_id=conversation.id,
        tenant_id=identity.tenant_id,
        role="user",
        content=content,
        generation_status="completed",
        created_at=created_at,
    )
    session.add(user_message)
    await session.flush()
    assistant_message = Message(
        conversation_id=conversation.id,
        tenant_id=identity.tenant_id,
        role="assistant",
        content="",
        in_reply_to_message_id=user_message.id,
        reply_version=1,
        generation_status="generating",
        is_current=True,
        created_at=created_at + timedelta(microseconds=1),
    )
    conversation.updated_at = assistant_message.created_at
    session.add(assistant_message)
    await session.commit()
    return conversation, assistant_message


async def get_owned_reply(
    session: AsyncSession,
    conversation_id: UUID,
    message_id: UUID,
    identity: CurrentIdentity,
) -> Message:
    """Find one assistant reply after applying the conversation ownership boundary."""

    await get_conversation(session, conversation_id, identity)
    statement = select(Message).where(
        Message.id == message_id,
        Message.conversation_id == conversation_id,
        Message.tenant_id == identity.tenant_id,
        Message.role == "assistant",
    )
    reply = (await session.execute(statement)).scalar_one_or_none()
    if reply is None:
        raise MessageNotFoundError
    return reply


async def create_regenerated_reply(
    session: AsyncSession,
    conversation_id: UUID,
    message_id: UUID,
    identity: CurrentIdentity,
) -> tuple[Conversation, Message]:
    """Create a new reply version without overwriting the selected historical reply."""

    previous_reply = await get_owned_reply(session, conversation_id, message_id, identity)
    if (
        previous_reply.in_reply_to_message_id is None
        or previous_reply.generation_status != "completed"
    ):
        raise MessageNotFoundError
    conversation = await get_conversation(session, conversation_id, identity)
    versions = await session.execute(
        select(Message.reply_version)
        .where(Message.in_reply_to_message_id == previous_reply.in_reply_to_message_id)
        .order_by(Message.reply_version.desc())
    )
    next_version = (versions.scalars().first() or 0) + 1
    created_at = utc_now()
    regenerated = Message(
        conversation_id=conversation.id,
        tenant_id=identity.tenant_id,
        role="assistant",
        content="",
        in_reply_to_message_id=previous_reply.in_reply_to_message_id,
        reply_version=next_version,
        generation_status="generating",
        is_current=False,
        created_at=created_at,
    )
    conversation.updated_at = created_at
    session.add(regenerated)
    await session.commit()
    return conversation, regenerated


async def get_reply_source_content(session: AsyncSession, reply: Message) -> str:
    """Return the persisted user input that a reply version answers."""

    if reply.in_reply_to_message_id is None:
        raise MessageNotFoundError
    source = await session.get(Message, reply.in_reply_to_message_id)
    if source is None or source.role != "user":
        raise MessageNotFoundError
    return source.content


async def cancel_reply(session: AsyncSession, reply: Message) -> Message:
    """Mark a running reply cancelled; completed replies keep their immutable history."""

    if reply.generation_status == "generating":
        reply.generation_status = "cancelled"
        reply.is_current = False
        await session.commit()
    return reply


async def stream_reply_chunks(session: AsyncSession, reply: Message, source_content: str):
    """Yield deterministic chunks while observing cancellation between every chunk."""

    for chunk in (f"Placeholder reply: {source_content}").split(" "):
        await asyncio.sleep(0.05)
        await session.refresh(reply)
        if reply.generation_status != "generating":
            return
        reply.content += (" " if reply.content else "") + chunk
        await session.commit()
        yield chunk
    previous_current = await session.execute(
        select(Message).where(
            Message.in_reply_to_message_id == reply.in_reply_to_message_id,
            Message.id != reply.id,
            Message.is_current.is_(True),
        )
    )
    for previous_reply in previous_current.scalars():
        previous_reply.is_current = False
    reply.generation_status = "completed"
    reply.is_current = True
    await session.commit()
