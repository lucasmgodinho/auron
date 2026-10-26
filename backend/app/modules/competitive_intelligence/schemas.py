from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .evidence import SourceProvenance
from .model import AnalysisRunStatus
from .telemetry_schemas import RunTelemetry

CompanyName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=200),
]


class CompetitiveAnalysisRequest(BaseModel):
    company_name: CompanyName

    model_config = ConfigDict(extra="forbid")


class CompetitiveAnalysisResponse(BaseModel):
    run_id: UUID
    company_name: str
    sector: str
    report: str


class AnalysisRunSummary(BaseModel):
    id: UUID
    organization_id: UUID
    requested_by_user_id: UUID
    company_name: str
    sector: str | None
    pipeline_version: str
    status: AnalysisRunStatus
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None

    model_config = ConfigDict(from_attributes=True)


class AnalysisRunSourceResponse(BaseModel):
    id: UUID
    source_key: str
    title: str
    url: str
    domain: str
    research_query: str
    provider_result_id: str | None
    provider_score: float | None
    provider_rank: int | None
    content_source: str | None
    published_date: datetime | None
    retrieved_at: datetime
    provenance: list[SourceProvenance]

    model_config = ConfigDict(from_attributes=True)


class AnalysisRunEvidenceResponse(BaseModel):
    evidence_id: str
    source_id: UUID
    chunk_id: str
    text: str
    query: str
    distance: float
    rank: int
    retrieval_rank: int
    cited: bool

    model_config = ConfigDict(from_attributes=True)


class AnalysisRunDetail(AnalysisRunSummary):
    report: str | None
    telemetry: RunTelemetry | None = None
    sources: list[AnalysisRunSourceResponse] = Field(default_factory=list)
    evidence: list[AnalysisRunEvidenceResponse] = Field(default_factory=list)


class AnalysisRunPage(BaseModel):
    items: list[AnalysisRunSummary]
    total: int
    limit: int
    offset: int


AnalysisEventType = Literal[
    "analysis_started",
    "questions_generated",
    "search_started",
    "search_completed",
    "search_failed",
    "documents_indexed",
    "rag_retrieved",
    "report_generation_started",
    "analysis_completed",
    "analysis_failed",
]


class AnalysisEvent(BaseModel):
    type: AnalysisEventType
    occurred_at: datetime
    data: dict[str, Any]


def create_analysis_event(
    event_type: AnalysisEventType,
    data: dict[str, Any],
) -> AnalysisEvent:
    return AnalysisEvent(
        type=event_type,
        occurred_at=datetime.now(UTC),
        data=data,
    )
