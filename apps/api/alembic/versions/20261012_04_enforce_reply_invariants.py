"""Validate historical lineage and enforce reply invariants.

Revision ID: 20261012_04
Revises: 20260923_03
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261012_04"
down_revision: str | None = "20260923_03"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Repair provable placeholder pairs; reject ambiguous history before constraints."""

    # The original M2-C reply contains its exact input. Recover it before trusting
    # the timestamp-only backfill in revision 03. Equal candidate times are ambiguous.
    op.execute("""
        DO $$
        DECLARE reply_row RECORD; source_id UUID; source_time TIMESTAMPTZ; candidate_count INT;
        BEGIN
          FOR reply_row IN SELECT * FROM messages
            WHERE role = 'assistant' AND reply_version = 1
              AND generation_status = 'completed'
          LOOP
            SELECT MAX(created_at) INTO source_time FROM messages
              WHERE role = 'user' AND conversation_id = reply_row.conversation_id
                AND tenant_id = reply_row.tenant_id AND created_at < reply_row.created_at
                AND 'Placeholder reply: ' || content = reply_row.content;
            SELECT COUNT(*) INTO candidate_count FROM messages
              WHERE role = 'user' AND conversation_id = reply_row.conversation_id
                AND tenant_id = reply_row.tenant_id AND created_at = source_time
                AND 'Placeholder reply: ' || content = reply_row.content;
            IF candidate_count <> 1 THEN
              RAISE EXCEPTION 'Ambiguous or unpaired placeholder history; migration stopped';
            END IF;
            SELECT id INTO source_id FROM messages
              WHERE role = 'user' AND conversation_id = reply_row.conversation_id
                AND tenant_id = reply_row.tenant_id AND created_at = source_time
                AND 'Placeholder reply: ' || content = reply_row.content;
            UPDATE messages SET in_reply_to_message_id = source_id WHERE id = reply_row.id;
          END LOOP;
          IF EXISTS (
            SELECT 1 FROM messages WHERE role = 'assistant'
              GROUP BY in_reply_to_message_id
              HAVING COUNT(*) <> COUNT(DISTINCT reply_version) AND MAX(reply_version) <> 1
          ) THEN
            RAISE EXCEPTION 'Conflicting existing version numbers; migration stopped';
          END IF;
          IF EXISTS (
            SELECT 1 FROM messages reply LEFT JOIN messages source
              ON source.id = reply.in_reply_to_message_id
            WHERE reply.role = 'assistant' AND (
              source.id IS NULL OR source.role <> 'user'
              OR source.tenant_id <> reply.tenant_id
              OR source.conversation_id <> reply.conversation_id
              OR source.created_at >= reply.created_at
              OR reply.reply_version IS NULL OR reply.reply_version < 1
            )
          ) THEN
            RAISE EXCEPTION 'Invalid reply lineage; migration stopped';
          END IF;
          IF EXISTS (
            SELECT 1 FROM messages WHERE role = 'assistant'
              GROUP BY in_reply_to_message_id, created_at HAVING COUNT(*) > 1
          ) THEN
            RAISE EXCEPTION 'Ambiguous reply version order; migration stopped';
          END IF;
          IF EXISTS (
            SELECT 1 FROM messages WHERE generation_status = 'generating'
              GROUP BY in_reply_to_message_id HAVING COUNT(*) > 1
          ) THEN
            RAISE EXCEPTION 'Multiple running replies; stop generators before migration';
          END IF;
        END $$;
    """)
    # Repair duplicate version 1 values produced by the old historical backfill.
    op.execute("""
        WITH duplicate_sources AS (
          SELECT in_reply_to_message_id FROM messages WHERE role = 'assistant'
          GROUP BY in_reply_to_message_id HAVING COUNT(*) <> COUNT(DISTINCT reply_version)
        ), versions AS (
          SELECT id, ROW_NUMBER() OVER (
            PARTITION BY in_reply_to_message_id ORDER BY created_at, id
          ) AS version FROM messages WHERE role = 'assistant'
            AND in_reply_to_message_id IN (SELECT in_reply_to_message_id FROM duplicate_sources)
        )
        UPDATE messages SET reply_version = versions.version
          FROM versions WHERE messages.id = versions.id
    """)
    op.execute("UPDATE messages SET is_current = FALSE WHERE role = 'assistant'")
    op.execute("""
        WITH current_replies AS (
          SELECT DISTINCT ON (in_reply_to_message_id) id FROM messages
          WHERE role = 'assistant' AND generation_status = 'completed'
          ORDER BY in_reply_to_message_id, reply_version DESC
        )
        UPDATE messages SET is_current = TRUE
          FROM current_replies WHERE messages.id = current_replies.id
    """)
    op.create_unique_constraint(
        "uq_messages_reply_version", "messages", ["in_reply_to_message_id", "reply_version"]
    )
    op.create_check_constraint(
        "ck_messages_reply_version", "messages", "reply_version IS NULL OR reply_version > 0"
    )
    op.create_check_constraint(
        "ck_messages_current_completed",
        "messages",
        "NOT is_current OR generation_status = 'completed'",
    )
    op.create_index(
        "uq_messages_reply_current",
        "messages",
        ["in_reply_to_message_id"],
        unique=True,
        postgresql_where=sa.text("role = 'assistant' AND is_current"),
    )
    op.create_index(
        "uq_messages_reply_generating",
        "messages",
        ["in_reply_to_message_id"],
        unique=True,
        postgresql_where=sa.text("generation_status = 'generating'"),
    )


def downgrade() -> None:
    """Remove new guards while preserving corrected lineage and message content."""

    op.drop_index("uq_messages_reply_generating", table_name="messages")
    op.drop_index("uq_messages_reply_current", table_name="messages")
    op.drop_constraint("ck_messages_current_completed", "messages", type_="check")
    op.drop_constraint("ck_messages_reply_version", "messages", type_="check")
    op.drop_constraint("uq_messages_reply_version", "messages", type_="unique")
