"""Request and response schemas for conversations."""

from datetime import datetime
from typing import Literal
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
    in_reply_to_message_id: UUID | None
    reply_version: int | None
    generation_status: str
    is_current: bool
    created_at: datetime


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    message_id: UUID
    rating: Literal["like", "dislike"]
    reason: str | None
    detail: str
    updated_at: datetime


class SummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    facts: list[dict[str, object]]
    content: str
    covered_message_ids: list[str]
    token_count: int


class ContextResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message_id: UUID
    selected_message_ids: list[str]
    input_token_count: int
    output_token_limit: int
    total_token_budget: int
    tokenizer_name: str
    tokenizer_version: str
    prompt_format_version: str
    summary: SummaryResponse | None = None


class CreateFeedbackRequest(BaseModel):
    rating: Literal["like", "dislike"]
    reason: Literal["incorrect", "irrelevant", "unclear", "other"] | None = None
    detail: str = Field(default="", max_length=500)


class ConversationDetailResponse(ConversationResponse):
    """Conversation metadata together with chronological messages."""

    messages: list[MessageResponse]
    feedback: list[FeedbackResponse] = Field(default_factory=list)
    contexts: list[ContextResponse] = Field(default_factory=list)


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
