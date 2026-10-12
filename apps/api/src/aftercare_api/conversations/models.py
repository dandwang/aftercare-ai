"""Persistent conversation and message models."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from aftercare_api.db.base import Base


def utc_now() -> datetime:
    """Provide an aware timestamp for deterministic message ordering."""

    return datetime.now(UTC)


class Conversation(Base):
    """A conversation owned by one user within one tenant."""

    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_tenant_owner_updated", "tenant_id", "owner_user_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )


class Message(Base):
    """An immutable user or assistant message in a conversation."""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
        CheckConstraint(
            "generation_status IN ('completed', 'generating', 'cancelled')",
            name="ck_messages_generation_status",
        ),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_messages_reply_current", "in_reply_to_message_id", "is_current"),
        UniqueConstraint(
            "in_reply_to_message_id", "reply_version", name="uq_messages_reply_version"
        ),
        CheckConstraint(
            "reply_version IS NULL OR reply_version > 0", name="ck_messages_reply_version"
        ),
        CheckConstraint(
            "NOT is_current OR generation_status = 'completed'",
            name="ck_messages_current_completed",
        ),
        Index(
            "uq_messages_reply_current",
            "in_reply_to_message_id",
            unique=True,
            postgresql_where=text("role = 'assistant' AND is_current"),
            sqlite_where=text("role = 'assistant' AND is_current"),
        ),
        Index(
            "uq_messages_reply_generating",
            "in_reply_to_message_id",
            unique=True,
            postgresql_where=text("generation_status = 'generating'"),
            sqlite_where=text("generation_status = 'generating'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    in_reply_to_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    reply_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_status: Mapped[str] = mapped_column(String(16), default="completed")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )
