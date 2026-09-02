"""Create structured application events.

Revision ID: 0007_create_application_events
Revises: 0006_create_module_platform
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_create_application_events"
down_revision: str | Sequence[str] | None = "0006_create_module_platform"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "application_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("event", sa.String(length=150), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("module", sa.String(length=100), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("resource_type", sa.String(length=100), nullable=True),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_application_events_organization_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_application_events_user_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_application_events_created_at",
        "application_events",
        ["created_at"],
    )
    op.create_index(
        "ix_application_events_organization_created_at",
        "application_events",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_application_events_request_id",
        "application_events",
        ["request_id"],
    )
    op.create_index(
        "ix_application_events_user_created_at",
        "application_events",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_application_events_user_created_at", table_name="application_events")
    op.drop_index("ix_application_events_request_id", table_name="application_events")
    op.drop_index(
        "ix_application_events_organization_created_at",
        table_name="application_events",
    )
    op.drop_index("ix_application_events_created_at", table_name="application_events")
    op.drop_table("application_events")
