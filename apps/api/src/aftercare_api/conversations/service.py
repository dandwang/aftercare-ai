"""Business operations for tenant-scoped conversations."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aftercare_api.conversations.models import Conversation, Message, utc_now
from aftercare_api.identity.service import CurrentIdentity


class ConversationNotFoundError(Exception):
    """Raised when a conversation is absent or inaccessible to the current identity."""


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
    assistant_message = Message(
        conversation_id=conversation.id,
        tenant_id=identity.tenant_id,
        role="assistant",
        content=f"Placeholder reply: {content}",
        created_at=created_at + timedelta(microseconds=1),
    )
    conversation.updated_at = assistant_message.created_at
    session.add_all((user_message, assistant_message))
    await session.commit()
    return conversation, [user_message, assistant_message]
