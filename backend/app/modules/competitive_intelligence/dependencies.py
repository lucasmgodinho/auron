from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import SessionLocal

from .question_generation import OpenAIQuestionGenerator
from .report_generation import OpenAIReportGenerator
from .search import TavilySearchClient
from .service import AnalysisRunService
from .vector_store import ChromaEvidenceStore
from .workflow import CompetitiveIntelligenceWorkflow


def get_analysis_run_session_factory() -> Callable[[], Session]:
    return SessionLocal


def get_analysis_run_service(
    session_factory: Annotated[Callable[[], Session], Depends(get_analysis_run_session_factory)],
) -> AnalysisRunService:
    return AnalysisRunService(session_factory)


def get_competitive_intelligence_workflow(
    settings: Annotated[Settings, Depends(get_settings)],
) -> CompetitiveIntelligenceWorkflow:
    if settings.openai_api_key is None or settings.tavily_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Competitive Intelligence is not configured",
        )

    openai_api_key = settings.openai_api_key.get_secret_value()
    base_url = str(settings.openai_base_url) if settings.openai_base_url else None
    return CompetitiveIntelligenceWorkflow(
        question_generator=OpenAIQuestionGenerator(
            api_key=openai_api_key,
            base_url=base_url,
        ),
        search_client=TavilySearchClient(api_key=settings.tavily_api_key.get_secret_value()),
        context_store=ChromaEvidenceStore(
            api_key=openai_api_key,
            base_url=base_url,
        ),
        report_generator=OpenAIReportGenerator(
            api_key=openai_api_key,
            base_url=base_url,
        ),
    )
