import logging
import re
from collections.abc import Callable, Iterator
from contextlib import closing
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.application_events.service import record_event

from . import repository
from .definition import MODULE_KEY
from .errors import (
    InvalidCompanyError,
    ModelProviderError,
    NoSearchResultsError,
    SearchProviderError,
    VectorStoreError,
)
from .evidence import SourceProvenance
from .model import AnalysisRunEvidence, AnalysisRunSource, AnalysisRunStatus, CompetitiveAnalysisRun
from .schemas import (
    AnalysisEvent,
    AnalysisRunDetail,
    AnalysisRunEvidenceResponse,
    AnalysisRunPage,
    AnalysisRunSourceResponse,
    AnalysisRunSummary,
    create_analysis_event,
)
from .workflow import CompetitiveAnalysisResult, CompetitiveIntelligenceWorkflow

PIPELINE_VERSION = "2.0.0"
logger = logging.getLogger(__name__)
FAILURE_MESSAGES = {
    "invalid_company": "Company could not be validated",
    "no_search_results": "No valid search results were found",
    "search_provider_failed": "Competitive search provider failed",
    "model_provider_failed": "Competitive analysis model failed",
    "vector_store_failed": "Competitive analysis context could not be prepared",
    "unexpected_error": "Competitive analysis failed unexpectedly",
}


class AnalysisRunNotFoundError(Exception):
    pass


class InvalidRunTransitionError(Exception):
    pass


class AnalysisExecutionError(Exception):
    def __init__(self, code: str, run_id: UUID) -> None:
        self.code = code
        self.run_id = run_id
        super().__init__(FAILURE_MESSAGES[code])


def failure_code(error: Exception) -> str:
    for error_type, code in (
        (InvalidCompanyError, "invalid_company"),
        (NoSearchResultsError, "no_search_results"),
        (SearchProviderError, "search_provider_failed"),
        (ModelProviderError, "model_provider_failed"),
        (VectorStoreError, "vector_store_failed"),
    ):
        if isinstance(error, error_type):
            return code
    return "unexpected_error"


def get_run(session: Session, *, organization_id: UUID, run_id: UUID) -> AnalysisRunDetail:
    run = repository.get_run(session, organization_id=organization_id, run_id=run_id)
    if run is None:
        raise AnalysisRunNotFoundError
    return AnalysisRunDetail(
        **AnalysisRunSummary.model_validate(run).model_dump(),
        report=run.report,
        sources=[
            AnalysisRunSourceResponse.model_validate(source)
            for source in repository.list_sources(
                session, organization_id=organization_id, run_id=run_id
            )
        ],
        evidence=[
            AnalysisRunEvidenceResponse.model_validate(evidence)
            for evidence in repository.list_evidence(
                session, organization_id=organization_id, run_id=run_id
            )
        ],
    )


def list_runs(
    session: Session,
    *,
    organization_id: UUID,
    limit: int,
    offset: int,
) -> AnalysisRunPage:
    items, total = repository.list_runs(
        session,
        organization_id=organization_id,
        limit=limit,
        offset=offset,
    )
    return AnalysisRunPage(
        items=[AnalysisRunSummary.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


class AnalysisRunService:
    """Durable domain lifecycle. No provider call holds a run database transaction."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def create_run(
        self,
        *,
        organization_id: UUID,
        requested_by_user_id: UUID,
        company_name: str,
    ) -> AnalysisRunSummary:
        with self._session_factory() as session:
            run = CompetitiveAnalysisRun(
                organization_id=organization_id,
                requested_by_user_id=requested_by_user_id,
                company_name=company_name,
                pipeline_version=PIPELINE_VERSION,
            )
            repository.add_run(session, run)
            response = AnalysisRunSummary.model_validate(run)
            session.commit()
            return response

    @staticmethod
    def _locked_run(
        session: Session,
        organization_id: UUID,
        run_id: UUID,
    ) -> CompetitiveAnalysisRun:
        run = repository.get_run(
            session,
            organization_id=organization_id,
            run_id=run_id,
            for_update=True,
        )
        if run is None:
            raise AnalysisRunNotFoundError
        return run

    def start_run(self, *, organization_id: UUID, run_id: UUID) -> None:
        with self._session_factory() as session:
            run = self._locked_run(session, organization_id, run_id)
            if run.status != AnalysisRunStatus.PENDING:
                raise InvalidRunTransitionError("Only pending runs can start")
            run.status = AnalysisRunStatus.RUNNING
            run.started_at = datetime.now(UTC)
            session.commit()

    def update_sector(self, *, organization_id: UUID, run_id: UUID, sector: str) -> None:
        with self._session_factory() as session:
            run = self._locked_run(session, organization_id, run_id)
            if run.status != AnalysisRunStatus.RUNNING:
                raise InvalidRunTransitionError("Only running runs can receive a sector")
            run.sector = sector
            session.commit()

    def complete_run(
        self,
        *,
        organization_id: UUID,
        run_id: UUID,
        result: CompetitiveAnalysisResult,
    ) -> None:
        with self._session_factory() as session:
            run = self._locked_run(session, organization_id, run_id)
            if run.status != AnalysisRunStatus.RUNNING:
                raise InvalidRunTransitionError("Only running runs can complete")
            if not result.report.strip() or not result.sector.strip():
                raise ValueError("Completed run requires a report and sector")
            sources = {}
            available_ids = {f"E{index}" for index in range(1, len(result.evidence) + 1)}
            cited_ids = set(re.findall(r"\[(E\d+)\]", result.report))
            if cited_ids - available_ids:
                raise ValueError("Report cites unknown evidence")
            for index, evidence in enumerate(result.evidence, start=1):
                source = evidence.source
                if source is None or source.source_id != evidence.source_id:
                    raise ValueError("Retrieved evidence requires matching source metadata")
                if source.source_id not in sources:
                    metadata = source.model_dump(include=set(SourceProvenance.model_fields))
                    source_key = metadata.pop("source_id")
                    metadata["url"] = str(source.url)
                    persisted = AnalysisRunSource(
                        organization_id=organization_id,
                        run_id=run_id,
                        source_key=source_key,
                        **metadata,
                        provenance=[
                            discovery.model_dump(mode="json")
                            for discovery in source.provenance
                            or [SourceProvenance(**metadata, source_id=source_key)]
                        ],
                    )
                    session.add(persisted)
                    session.flush()
                    sources[source.source_id] = persisted.id
                session.add(
                    AnalysisRunEvidence(
                        organization_id=organization_id,
                        run_id=run_id,
                        source_id=sources[source.source_id],
                        evidence_id=f"E{index}",
                        chunk_id=evidence.chunk_id,
                        text=evidence.text,
                        query=evidence.query,
                        distance=evidence.distance,
                        rank=index,
                        retrieval_rank=evidence.rank,
                        cited=f"E{index}" in cited_ids,
                    )
                )
            run.sector = result.sector
            run.report = result.report
            run.status = AnalysisRunStatus.COMPLETED
            run.completed_at = datetime.now(UTC)
            session.commit()

    def fail_run(self, *, organization_id: UUID, run_id: UUID, code: str) -> None:
        code = code if code in FAILURE_MESSAGES else "unexpected_error"
        with self._session_factory() as session:
            run = self._locked_run(session, organization_id, run_id)
            if run.status not in {AnalysisRunStatus.PENDING, AnalysisRunStatus.RUNNING}:
                raise InvalidRunTransitionError("Only active runs can fail")
            run.started_at = run.started_at or datetime.now(UTC)
            run.status = AnalysisRunStatus.FAILED
            run.completed_at = datetime.now(UTC)
            run.error_code = code
            run.error_message = FAILURE_MESSAGES[code]
            session.commit()

    def cancel_if_active(self, *, organization_id: UUID, run_id: UUID) -> None:
        with self._session_factory() as session:
            run = self._locked_run(session, organization_id, run_id)
            if run.status not in {AnalysisRunStatus.PENDING, AnalysisRunStatus.RUNNING}:
                return
            run.status = AnalysisRunStatus.CANCELLED
            run.completed_at = datetime.now(UTC)
            run.error_code = "cancelled"
            run.error_message = "Analysis execution was cancelled"
            session.commit()

    @staticmethod
    def _record(
        run: AnalysisRunSummary,
        stage: str,
        started: float,
        code: str | None = None,
    ) -> None:
        record_event(
            level="error" if code else "info",
            event=f"competitive_intelligence.analysis.{stage}",
            category="business",
            module=MODULE_KEY,
            organization_id=run.organization_id,
            user_id=run.requested_by_user_id,
            resource_type="competitive_analysis_run",
            resource_id=run.id,
            status="failed" if code else "succeeded" if stage == "completed" else stage,
            duration_ms=round((perf_counter() - started) * 1000),
            error_code=code,
            error_message=FAILURE_MESSAGES.get(code) if code else None,
        )

    def stream_run(
        self,
        run: AnalysisRunSummary,
        workflow: CompetitiveIntelligenceWorkflow,
    ) -> Iterator[AnalysisEvent]:
        started = perf_counter()
        completed = False
        iterator = None

        def complete(result: CompetitiveAnalysisResult) -> None:
            nonlocal completed
            self.complete_run(organization_id=run.organization_id, run_id=run.id, result=result)
            completed = True

        try:
            self.start_run(organization_id=run.organization_id, run_id=run.id)
            self._record(run, "started", started)
            iterator = workflow.stream_analysis(
                organization_id=run.organization_id,
                company_name=run.company_name,
                run_id=run.id,
                on_completed=complete,
            )
            for event in iterator:
                if event.type == "questions_generated":
                    self.update_sector(
                        organization_id=run.organization_id,
                        run_id=run.id,
                        sector=event.data["sector"],
                    )
                elif event.type == "analysis_completed":
                    if not completed:
                        raise ValueError("Workflow completed without a domain result")
                    self._record(run, "completed", started)
                elif event.type == "analysis_failed":
                    code = event.data.get("code", "unexpected_error")
                    raise AnalysisExecutionError(
                        code
                        if isinstance(code, str) and code in FAILURE_MESSAGES
                        else "unexpected_error",
                        run.id,
                    )
                yield event.model_copy(update={"data": {**event.data, "run_id": str(run.id)}})
                if event.type == "analysis_completed":
                    return
            raise RuntimeError("Analysis stream ended without a terminal event")
        except Exception as error:
            code = error.code if isinstance(error, AnalysisExecutionError) else failure_code(error)
            if code == "unexpected_error":
                logger.exception("Competitive analysis run %s failed", run.id)
            self.fail_run(organization_id=run.organization_id, run_id=run.id, code=code)
            self._record(run, "failed", started, code)
            yield create_analysis_event("analysis_failed", {"code": code, "run_id": str(run.id)})
        finally:
            try:
                if iterator is not None:
                    iterator.close()
            finally:
                self.cancel_if_active(organization_id=run.organization_id, run_id=run.id)

    def execute(
        self,
        run: AnalysisRunSummary,
        workflow: CompetitiveIntelligenceWorkflow,
    ) -> AnalysisRunDetail:
        with closing(self.stream_run(run, workflow)) as iterator:
            for event in iterator:
                if event.type == "analysis_failed":
                    raise AnalysisExecutionError(event.data["code"], run.id)
        with self._session_factory() as session:
            return get_run(session, organization_id=run.organization_id, run_id=run.id)
