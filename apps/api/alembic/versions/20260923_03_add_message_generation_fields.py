"""Add streaming lifecycle and reply version fields.

Revision ID: 20260923_03
Revises: 20260923_02
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260923_03"
down_revision: str | None = "20260923_02"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Add reply lineage and generation state without dropping message history."""

    op.add_column("messages", sa.Column("in_reply_to_message_id", sa.Uuid(), nullable=True))
    op.add_column("messages", sa.Column("reply_version", sa.Integer(), nullable=True))
    op.add_column(
        "messages",
        sa.Column(
            "generation_status", sa.String(length=16), server_default="completed", nullable=False
        ),
    )
    op.add_column(
        "messages", sa.Column("is_current", sa.Boolean(), server_default=sa.true(), nullable=False)
    )
    op.execute(
        """
        UPDATE messages AS assistant
        SET in_reply_to_message_id = (
            SELECT user_message.id
            FROM messages AS user_message
            WHERE user_message.conversation_id = assistant.conversation_id
              AND user_message.role = 'user'
              AND user_message.created_at <= assistant.created_at
            ORDER BY user_message.created_at DESC, user_message.id DESC
            LIMIT 1
        ),
        reply_version = 1
        WHERE assistant.role = 'assistant'
        """
    )
    op.create_foreign_key(
        "fk_messages_in_reply_to_message_id",
        "messages",
        "messages",
        ["in_reply_to_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_messages_generation_status",
        "messages",
        "generation_status IN ('completed', 'generating', 'cancelled')",
    )
    op.create_index(
        "ix_messages_reply_current",
        "messages",
        ["in_reply_to_message_id", "is_current"],
        unique=False,
    )


def downgrade() -> None:
    """Remove M2-D lifecycle metadata while retaining original messages."""

    op.drop_index("ix_messages_reply_current", table_name="messages")
    op.drop_constraint("ck_messages_generation_status", "messages", type_="check")
    op.drop_constraint("fk_messages_in_reply_to_message_id", "messages", type_="foreignkey")
    op.drop_column("messages", "is_current")
    op.drop_column("messages", "generation_status")
    op.drop_column("messages", "reply_version")
    op.drop_column("messages", "in_reply_to_message_id")
