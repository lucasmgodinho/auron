from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .model import AnalysisRunEvidence, AnalysisRunSource, CompetitiveAnalysisRun


def add_run(session: Session, run: CompetitiveAnalysisRun) -> None:
    session.add(run)
    session.flush()


def get_run(
    session: Session,
    *,
    organization_id: UUID,
    run_id: UUID,
    for_update: bool = False,
) -> CompetitiveAnalysisRun | None:
    statement = select(CompetitiveAnalysisRun).where(
        CompetitiveAnalysisRun.organization_id == organization_id,
        CompetitiveAnalysisRun.id == run_id,
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return session.scalar(statement)


def list_runs(
    session: Session,
    *,
    organization_id: UUID,
    limit: int,
    offset: int,
) -> tuple[list[CompetitiveAnalysisRun], int]:
    scoped = CompetitiveAnalysisRun.organization_id == organization_id
    total = session.scalar(select(func.count()).select_from(CompetitiveAnalysisRun).where(scoped))
    items = list(
        session.scalars(
            select(CompetitiveAnalysisRun)
            .where(scoped)
            .order_by(CompetitiveAnalysisRun.created_at.desc(), CompetitiveAnalysisRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return items, total or 0


def list_sources(
    session: Session,
    *,
    organization_id: UUID,
    run_id: UUID,
) -> list[AnalysisRunSource]:
    return list(
        session.scalars(
            select(AnalysisRunSource)
            .where(
                AnalysisRunSource.organization_id == organization_id,
                AnalysisRunSource.run_id == run_id,
            )
            .order_by(AnalysisRunSource.source_key)
        )
    )


def list_evidence(
    session: Session,
    *,
    organization_id: UUID,
    run_id: UUID,
) -> list[AnalysisRunEvidence]:
    return list(
        session.scalars(
            select(AnalysisRunEvidence)
            .where(
                AnalysisRunEvidence.organization_id == organization_id,
                AnalysisRunEvidence.run_id == run_id,
            )
            .order_by(AnalysisRunEvidence.rank)
        )
    )
