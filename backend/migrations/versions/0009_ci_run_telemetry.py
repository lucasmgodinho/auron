"""Add compact run telemetry, scoped through its existing parent run.

Revision ID: 0009_ci_run_telemetry
Revises: 0008_create_ci_runs
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_ci_run_telemetry"
down_revision = "0008_create_ci_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "competitive_analysis_runs", sa.Column("telemetry", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("competitive_analysis_runs", "telemetry")
