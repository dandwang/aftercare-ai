"""HTTP endpoints for tenant-scoped conversations."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from aftercare_api.conversations.schemas import (
    ConversationDetailResponse,
    ConversationResponse,
    CreateMessageRequest,
)
from aftercare_api.conversations.service import (
    ConversationNotFoundError,
    add_message_pair,
    create_conversation,
    get_conversation,
    list_conversations,
    list_messages,
)
from aftercare_api.db.session import get_session
from aftercare_api.identity.dependencies import require_current_identity
from aftercare_api.identity.service import CurrentIdentity

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])
not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")


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
