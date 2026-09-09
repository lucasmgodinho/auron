from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

CompanyName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=200),
]


class CompetitiveAnalysisRequest(BaseModel):
    company_name: CompanyName

    model_config = ConfigDict(extra="forbid")


class CompetitiveAnalysisResponse(BaseModel):
    company_name: str
    sector: str
    report: str


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
