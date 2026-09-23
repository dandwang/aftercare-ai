"""Request and response schemas for conversations."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConversationResponse(BaseModel):
    """Persisted conversation metadata."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    """One persisted conversation message."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: str
    content: str
    created_at: datetime


class ConversationDetailResponse(ConversationResponse):
    """Conversation metadata together with chronological messages."""

    messages: list[MessageResponse]


class CreateMessageRequest(BaseModel):
    """User content to persist before creating a deterministic placeholder reply."""

    content: str = Field(max_length=4000)

    @field_validator("content")
    @classmethod
    def require_non_blank_content(cls, value: str) -> str:
        """Reject whitespace-only messages and normalize intentional surrounding whitespace."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("Message content must not be blank")
        return normalized
