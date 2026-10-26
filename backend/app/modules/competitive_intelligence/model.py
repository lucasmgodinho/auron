from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AnalysisRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CompetitiveAnalysisRun(Base):
    __tablename__ = "competitive_analysis_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_ci_runs_organization_id"),
        Index("ix_ci_runs_organization_created_at", "organization_id", "created_at", "id"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_ci_runs_status",
        ),
        CheckConstraint(
            "(status IN ('pending', 'running') AND completed_at IS NULL) OR "
            "(status IN ('completed', 'failed', 'cancelled') AND completed_at IS NOT NULL)",
            name="ck_ci_runs_terminal_timestamp",
        ),
        CheckConstraint(
            "status NOT IN ('running', 'completed', 'failed') OR started_at IS NOT NULL",
            name="ck_ci_runs_started_timestamp",
        ),
        CheckConstraint(
            "(status = 'completed' AND report IS NOT NULL AND sector IS NOT NULL) OR "
            "(status <> 'completed' AND report IS NULL)",
            name="ck_ci_runs_report",
        ),
        CheckConstraint("status <> 'failed' OR error_code IS NOT NULL", name="ck_ci_runs_error"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", name="fk_ci_runs_organization", ondelete="CASCADE"),
    )
    requested_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", name="fk_ci_runs_requested_by"),
    )
    company_name: Mapped[str] = mapped_column(String(200))
    sector: Mapped[str | None] = mapped_column(String(255))
    pipeline_version: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default=AnalysisRunStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    report: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(String(500))
    telemetry: Mapped[dict | None] = mapped_column(JSONB)


class AnalysisRunSource(Base):
    """Run-local source metadata, without summaries or full web pages."""

    __tablename__ = "competitive_analysis_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "run_id"],
            ["competitive_analysis_runs.organization_id", "competitive_analysis_runs.id"],
            name="fk_ci_sources_run",
            ondelete="CASCADE",
        ),
        UniqueConstraint("organization_id", "run_id", "id", name="uq_ci_sources_run_id"),
        UniqueConstraint("organization_id", "run_id", "source_key", name="uq_ci_sources_key"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    source_key: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(255))
    research_query: Mapped[str] = mapped_column(Text)
    provider_result_id: Mapped[str | None] = mapped_column(Text)
    provider_score: Mapped[float | None] = mapped_column(Float)
    provider_rank: Mapped[int | None] = mapped_column(Integer)
    content_source: Mapped[str | None] = mapped_column(String(50))
    published_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provenance: Mapped[list[dict]] = mapped_column(JSONB, default=list)


class AnalysisRunEvidence(Base):
    """Only unique chunks supplied to the report, with their citation mapping."""

    __tablename__ = "competitive_analysis_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "run_id", "source_id"],
            [
                "competitive_analysis_sources.organization_id",
                "competitive_analysis_sources.run_id",
                "competitive_analysis_sources.id",
            ],
            name="fk_ci_evidence_source",
            ondelete="CASCADE",
        ),
        UniqueConstraint("organization_id", "run_id", "evidence_id", name="uq_ci_evidence_id"),
        UniqueConstraint("organization_id", "run_id", "chunk_id", name="uq_ci_evidence_chunk"),
        CheckConstraint("rank > 0", name="ck_ci_evidence_rank"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    source_id: Mapped[UUID] = mapped_column(Uuid)
    evidence_id: Mapped[str] = mapped_column(String(50))
    chunk_id: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    query: Mapped[str] = mapped_column(Text)
    distance: Mapped[float] = mapped_column(Float)
    rank: Mapped[int] = mapped_column(Integer)
    retrieval_rank: Mapped[int] = mapped_column(Integer)
    cited: Mapped[bool] = mapped_column(Boolean)
