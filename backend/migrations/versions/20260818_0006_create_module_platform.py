"""Create module entitlements and Organization access groups.

Revision ID: 0006_create_module_platform
Revises: 0005_create_local_auth
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_create_module_platform"
down_revision: str | Sequence[str] | None = "0005_create_local_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organization_modules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("module_key", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_organization_modules_organization_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "module_key",
            name="uq_organization_modules_organization_module",
        ),
    )
    op.create_table(
        "organization_access_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_organization_access_groups_organization_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "name",
            name="uq_organization_access_groups_organization_name",
        ),
    )
    op.create_table(
        "organization_access_group_permissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("access_group_id", sa.Uuid(), nullable=False),
        sa.Column("permission_key", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["access_group_id"],
            ["organization_access_groups.id"],
            name="fk_organization_access_group_permissions_group_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "access_group_id",
            "permission_key",
            name="uq_organization_access_group_permissions_group_permission",
        ),
    )
    op.create_table(
        "organization_membership_access_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_membership_id", sa.Uuid(), nullable=False),
        sa.Column("access_group_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["access_group_id"],
            ["organization_access_groups.id"],
            name="fk_organization_membership_access_groups_group_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_membership_id"],
            ["organization_memberships.id"],
            name="fk_organization_membership_access_groups_membership_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_membership_id",
            "access_group_id",
            name="uq_organization_membership_access_groups_membership_group",
        ),
    )
    op.create_index(
        "ix_organization_membership_access_groups_access_group_id",
        "organization_membership_access_groups",
        ["access_group_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_organization_membership_access_groups_access_group_id",
        table_name="organization_membership_access_groups",
    )
    op.drop_table("organization_membership_access_groups")
    op.drop_table("organization_access_group_permissions")
    op.drop_table("organization_access_groups")
    op.drop_table("organization_modules")
