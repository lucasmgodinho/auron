"""create competitive analysis runs

Revision ID: 0008_create_ci_runs
Revises: 0007_create_application_events
Create Date: 2026-10-05 14:15:55.889741
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_create_ci_runs"
down_revision: str | Sequence[str] | None = "0007_create_application_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "competitive_analysis_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("sector", sa.String(length=255), nullable=True),
        sa.Column("pipeline_version", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("report", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "(status = 'completed' AND report IS NOT NULL AND sector IS NOT NULL) OR "
            "(status <> 'completed' AND report IS NULL)",
            name="ck_ci_runs_report",
        ),
        sa.CheckConstraint(
            "(status IN ('pending', 'running') AND completed_at IS NULL) OR "
            "(status IN ('completed', 'failed', 'cancelled') AND completed_at IS NOT NULL)",
            name="ck_ci_runs_terminal_timestamp",
        ),
        sa.CheckConstraint("status <> 'failed' OR error_code IS NOT NULL", name="ck_ci_runs_error"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_ci_runs_status",
        ),
        sa.CheckConstraint(
            "status NOT IN ('running', 'completed', 'failed') OR started_at IS NOT NULL",
            name="ck_ci_runs_started_timestamp",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_ci_runs_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"], name="fk_ci_runs_requested_by"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id", name="uq_ci_runs_organization_id"),
    )
    op.create_index(
        "ix_ci_runs_organization_created_at",
        "competitive_analysis_runs",
        ["organization_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "competitive_analysis_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("source_key", sa.String(length=255), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("research_query", sa.Text(), nullable=False),
        sa.Column("provider_result_id", sa.Text(), nullable=True),
        sa.Column("provider_score", sa.Float(), nullable=True),
        sa.Column("provider_rank", sa.Integer(), nullable=True),
        sa.Column("content_source", sa.String(length=50), nullable=True),
        sa.Column("published_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "run_id"],
            ["competitive_analysis_runs.organization_id", "competitive_analysis_runs.id"],
            name="fk_ci_sources_run",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "run_id", "id", name="uq_ci_sources_run_id"),
        sa.UniqueConstraint("organization_id", "run_id", "source_key", name="uq_ci_sources_key"),
    )
    op.create_table(
        "competitive_analysis_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.String(length=50), nullable=False),
        sa.Column("chunk_id", sa.String(length=255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("distance", sa.Float(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("retrieval_rank", sa.Integer(), nullable=False),
        sa.Column("cited", sa.Boolean(), nullable=False),
        sa.CheckConstraint("rank > 0", name="ck_ci_evidence_rank"),
        sa.ForeignKeyConstraint(
            ["organization_id", "run_id", "source_id"],
            [
                "competitive_analysis_sources.organization_id",
                "competitive_analysis_sources.run_id",
                "competitive_analysis_sources.id",
            ],
            name="fk_ci_evidence_source",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "run_id", "chunk_id", name="uq_ci_evidence_chunk"),
        sa.UniqueConstraint("organization_id", "run_id", "evidence_id", name="uq_ci_evidence_id"),
    )


def downgrade() -> None:
    op.drop_table("competitive_analysis_evidence")
    op.drop_table("competitive_analysis_sources")
    op.drop_index("ix_ci_runs_organization_created_at", table_name="competitive_analysis_runs")
    op.drop_table("competitive_analysis_runs")
