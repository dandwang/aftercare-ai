"""Add tenant-scoped API audit metadata.

Revision ID: 20261012_06
Revises: 20261012_05
"""

import sqlalchemy as sa

from alembic import op

revision = "20261012_06"
down_revision = "20261012_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor_role", sa.String(32), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "result IN ('success', 'accepted', 'denied', 'failure')", name="ck_audit_events_result"
        ),
    )
    op.create_index(
        "ix_audit_events_tenant_created", "audit_events", ["tenant_id", "created_at", "id"]
    )


def downgrade() -> None:
    op.drop_table("audit_events")
