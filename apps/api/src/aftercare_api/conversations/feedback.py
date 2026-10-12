"""Persist feedback after checking trusted conversation and reply ownership."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aftercare_api.conversations.models import MessageFeedback, utc_now
from aftercare_api.conversations.schemas import CreateFeedbackRequest
from aftercare_api.conversations.service import MessageNotFoundError, get_owned_reply
from aftercare_api.identity.service import CurrentIdentity


async def save_feedback(
    session: AsyncSession,
    conversation_id: UUID,
    message_id: UUID,
    identity: CurrentIdentity,
    payload: CreateFeedbackRequest,
) -> MessageFeedback:
    reply = await get_owned_reply(session, conversation_id, message_id, identity)
    if reply.generation_status != "completed":
        raise MessageNotFoundError
    feedback = await session.scalar(
        select(MessageFeedback).where(
            MessageFeedback.message_id == message_id,
            MessageFeedback.actor_user_id == identity.user_id,
            MessageFeedback.tenant_id == identity.tenant_id,
        )
    )
    if feedback is None:
        feedback = MessageFeedback(
            message_id=message_id,
            conversation_id=conversation_id,
            tenant_id=identity.tenant_id,
            actor_user_id=identity.user_id,
        )
        session.add(feedback)
    feedback.rating = payload.rating
    feedback.reason = payload.reason
    feedback.detail = payload.detail.strip()
    feedback.updated_at = utc_now()
    await session.commit()
    return feedback
