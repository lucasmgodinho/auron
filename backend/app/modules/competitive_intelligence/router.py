from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.access_control.dependencies import (
    ModuleAccessContext,
    require_module_permission,
)

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
    try:
        result = workflow.analyze(
            organization_id=access.organization_context.organization.id,
            company_name=payload.company_name,
        )
    except InvalidCompanyError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Company could not be validated",
        ) from error
    except NoSearchResultsError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No valid search results were found",
        ) from error
    except SearchProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Competitive search provider failed",
        ) from error
    except ModelProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Competitive analysis model failed",
        ) from error
    except VectorStoreError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Competitive analysis context could not be prepared",
        ) from error

    return CompetitiveAnalysisResponse(
        company_name=result.company_name,
        sector=result.sector,
        report=result.report,
    )
