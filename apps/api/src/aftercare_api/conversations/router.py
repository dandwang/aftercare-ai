"""HTTP endpoints for tenant-scoped conversations."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from aftercare_api.conversations.models import Message
from aftercare_api.conversations.schemas import (
    ConversationDetailResponse,
    ConversationResponse,
    CreateMessageRequest,
    MessageResponse,
)
from aftercare_api.conversations.service import (
    ConversationNotFoundError,
    MessageNotFoundError,
    add_message_pair,
    cancel_reply,
    create_conversation,
    create_regenerated_reply,
    create_streaming_reply,
    get_conversation,
    get_owned_reply,
    get_reply_source_content,
    list_conversations,
    list_messages,
    stream_reply_chunks,
)
from aftercare_api.db.session import get_session
from aftercare_api.identity.dependencies import require_current_identity
from aftercare_api.identity.service import CurrentIdentity

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])
not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")


def sse_event(event: str, payload: dict[str, object]) -> str:
    """Encode one UTF-8 server-sent event with JSON data."""

    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


async def reply_event_stream(
    request: Request,
    session: AsyncSession,
    reply: Message,
    source_content: str,
) -> AsyncIterator[str]:
    """Stream reply lifecycle events and persist cancellation after disconnects."""

    response_message = MessageResponse.model_validate(reply).model_dump(mode="json")
    yield sse_event("started", {"message": response_message})
    try:
        async for chunk in stream_reply_chunks(session, reply, source_content):
            if await request.is_disconnected():
                await cancel_reply(session, reply)
                return
            yield sse_event("delta", {"message_id": str(reply.id), "content": chunk})
        await session.refresh(reply)
        event = "completed" if reply.generation_status == "completed" else "cancelled"
        response_message = MessageResponse.model_validate(reply).model_dump(mode="json")
        yield sse_event(event, {"message": response_message})
    except asyncio.CancelledError:
        await cancel_reply(session, reply)
        raise
    finally:
        await session.refresh(reply)
        if reply.generation_status == "generating":
            await cancel_reply(session, reply)


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation_endpoint(
    identity: Annotated[CurrentIdentity, Depends(require_current_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConversationResponse:
    """Create a conversation for the authenticated user in their trusted tenant."""

    return ConversationResponse.model_validate(await create_conversation(session, identity))


@router.get("", response_model=list[ConversationResponse])
async def list_conversations_endpoint(
    identity: Annotated[CurrentIdentity, Depends(require_current_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ConversationResponse]:
    """List conversations without exposing other users' or tenants' resources."""

    conversations = await list_conversations(session, identity)
    return [ConversationResponse.model_validate(conversation) for conversation in conversations]


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation_endpoint(
    conversation_id: UUID,
    identity: Annotated[CurrentIdentity, Depends(require_current_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConversationDetailResponse:
    """Return one owned conversation and its persisted messages."""

    try:
        conversation = await get_conversation(session, conversation_id, identity)
    except ConversationNotFoundError:
        raise not_found from None
    messages = await list_messages(session, conversation.id)
    return ConversationDetailResponse(
        **ConversationResponse.model_validate(conversation).model_dump(),
        messages=messages,
    )


@router.post("/{conversation_id}/messages", response_model=ConversationDetailResponse)
async def add_message_endpoint(
    conversation_id: UUID,
    payload: CreateMessageRequest,
    identity: Annotated[CurrentIdentity, Depends(require_current_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConversationDetailResponse:
    """Persist a message pair using the M2-C deterministic reply contract."""

    try:
        conversation, _ = await add_message_pair(
            session, conversation_id, payload.content, identity
        )
    except ConversationNotFoundError:
        raise not_found from None
    messages = await list_messages(session, conversation.id)
    return ConversationDetailResponse(
        **ConversationResponse.model_validate(conversation).model_dump(),
        messages=messages,
    )


@router.post("/{conversation_id}/messages/stream")
async def stream_message_endpoint(
    conversation_id: UUID,
    payload: CreateMessageRequest,
    request: Request,
    identity: Annotated[CurrentIdentity, Depends(require_current_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StreamingResponse:
    """Persist a user message then stream its deterministic assistant reply over SSE."""

    try:
        _, reply = await create_streaming_reply(session, conversation_id, payload.content, identity)
    except ConversationNotFoundError:
        raise not_found from None
    return StreamingResponse(
        reply_event_stream(request, session, reply, payload.content),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{conversation_id}/messages/{message_id}/stop", response_model=MessageResponse)
async def stop_message_endpoint(
    conversation_id: UUID,
    message_id: UUID,
    identity: Annotated[CurrentIdentity, Depends(require_current_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MessageResponse:
    """Stop a running assistant reply without mutating completed reply history."""

    try:
        reply = await get_owned_reply(session, conversation_id, message_id, identity)
    except (ConversationNotFoundError, MessageNotFoundError):
        raise not_found from None
    return MessageResponse.model_validate(await cancel_reply(session, reply))


@router.post("/{conversation_id}/messages/{message_id}/regenerate/stream")
async def regenerate_message_endpoint(
    conversation_id: UUID,
    message_id: UUID,
    request: Request,
    identity: Annotated[CurrentIdentity, Depends(require_current_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StreamingResponse:
    """Create and stream a new immutable version of a completed assistant reply."""

    try:
        _, reply = await create_regenerated_reply(session, conversation_id, message_id, identity)
        source_content = await get_reply_source_content(session, reply)
    except (ConversationNotFoundError, MessageNotFoundError):
        raise not_found from None
    return StreamingResponse(
        reply_event_stream(request, session, reply, source_content),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
