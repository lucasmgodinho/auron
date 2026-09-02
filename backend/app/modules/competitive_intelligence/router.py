from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.access_control.dependencies import (
    ModuleAccessContext,
    require_module_permission,
)
from app.core.application_events.service import record_event

from .definition import MODULE_KEY, RUN_ANALYSIS_PERMISSION
from .dependencies import get_competitive_intelligence_workflow
from .errors import (
    InvalidCompanyError,
    ModelProviderError,
    NoSearchResultsError,
    SearchProviderError,
    VectorStoreError,
)
from .schemas import CompetitiveAnalysisRequest, CompetitiveAnalysisResponse
from .workflow import CompetitiveIntelligenceWorkflow

router = APIRouter(tags=["competitive intelligence"])
require_analysis_access = require_module_permission(
    module_key=MODULE_KEY,
    permission_key=RUN_ANALYSIS_PERMISSION,
)


@router.post(
    "/organizations/{organization_id}/modules/competitive-intelligence/analyses",
    response_model=CompetitiveAnalysisResponse,
)
def run_competitive_analysis(
    payload: CompetitiveAnalysisRequest,
    access: Annotated[ModuleAccessContext, Depends(require_analysis_access)],
    workflow: Annotated[
        CompetitiveIntelligenceWorkflow,
        Depends(get_competitive_intelligence_workflow),
    ],
) -> CompetitiveAnalysisResponse:
    started_at = perf_counter()
    organization_id = access.organization_context.organization.id
    record_event(
        level="info",
        event="competitive_intelligence.analysis.started",
        category="business",
        module=MODULE_KEY,
        organization_id=organization_id,
        status="started",
    )
    try:
        result = workflow.analyze(
            organization_id=organization_id,
            company_name=payload.company_name,
        )
    except InvalidCompanyError as error:
        _record_analysis_failure(
            organization_id,
            started_at,
            "invalid_company",
            "Company could not be validated",
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Company could not be validated",
        ) from error
    except NoSearchResultsError as error:
        _record_analysis_failure(
            organization_id,
            started_at,
            "no_search_results",
            "No valid search results were found",
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No valid search results were found",
        ) from error
    except SearchProviderError as error:
        _record_analysis_failure(
            organization_id,
            started_at,
            "search_provider_failed",
            "Competitive search provider failed",
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Competitive search provider failed",
        ) from error
    except ModelProviderError as error:
        _record_analysis_failure(
            organization_id,
            started_at,
            "model_provider_failed",
            "Competitive analysis model failed",
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Competitive analysis model failed",
        ) from error
    except VectorStoreError as error:
        _record_analysis_failure(
            organization_id,
            started_at,
            "vector_store_failed",
            "Competitive analysis context could not be prepared",
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Competitive analysis context could not be prepared",
        ) from error
    except Exception:
        _record_analysis_failure(
            organization_id,
            started_at,
            "unexpected_error",
            "Competitive analysis failed unexpectedly",
        )
        raise

    record_event(
        level="info",
        event="competitive_intelligence.analysis.completed",
        category="business",
        module=MODULE_KEY,
        organization_id=organization_id,
        status="succeeded",
        duration_ms=round((perf_counter() - started_at) * 1000),
    )

    return CompetitiveAnalysisResponse(
        company_name=result.company_name,
        sector=result.sector,
        report=result.report,
    )


def _record_analysis_failure(
    organization_id: UUID,
    started_at: float,
    error_code: str,
    error_message: str,
) -> None:
    record_event(
        level="error",
        event="competitive_intelligence.analysis.failed",
        category="business",
        module=MODULE_KEY,
        organization_id=organization_id,
        status="failed",
        duration_ms=round((perf_counter() - started_at) * 1000),
        error_code=error_code,
        error_message=error_message,
    )
