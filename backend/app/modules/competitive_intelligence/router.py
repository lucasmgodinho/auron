from collections.abc import AsyncIterator, Iterator
from typing import Annotated
from uuid import UUID

from anyio import CancelScope
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool
from starlette.types import Receive, Scope, Send

from app.core.access_control.dependencies import ModuleAccessContext, require_module_permission
from app.database import get_session

from . import service
from .definition import MODULE_KEY, RUN_ANALYSIS_PERMISSION
from .dependencies import get_analysis_run_service, get_competitive_intelligence_workflow
from .schemas import (
    AnalysisEvent,
    AnalysisRunDetail,
    AnalysisRunPage,
    AnalysisRunSummary,
    CompetitiveAnalysisRequest,
    CompetitiveAnalysisResponse,
)
from .service import AnalysisRunService
from .workflow import CompetitiveIntelligenceWorkflow

router = APIRouter(tags=["competitive intelligence"])
require_analysis_access = require_module_permission(
    module_key=MODULE_KEY,
    permission_key=RUN_ANALYSIS_PERMISSION,
)
AnalysisAccess = Annotated[ModuleAccessContext, Depends(require_analysis_access)]
RunService = Annotated[AnalysisRunService, Depends(get_analysis_run_service)]
Workflow = Annotated[
    CompetitiveIntelligenceWorkflow, Depends(get_competitive_intelligence_workflow)
]
SessionDependency = Annotated[Session, Depends(get_session)]
BASE_PATH = "/organizations/{organization_id}/modules/competitive-intelligence/analyses"


async def _stream_lines(
    iterator: Iterator[AnalysisEvent],
) -> AsyncIterator[str]:
    try:
        async for event in iterate_in_threadpool(iterator):
            yield event.model_dump_json() + "\n"
    finally:
        # Streaming disconnect cancellation must not interrupt the status transaction.
        with CancelScope(shield=True):
            await run_in_threadpool(iterator.close)


class AnalysisRunStreamingResponse(StreamingResponse):
    """Close the execution even when sending headers fails before iteration begins."""

    def __init__(
        self,
        run_service: AnalysisRunService,
        run: AnalysisRunSummary,
        workflow: CompetitiveIntelligenceWorkflow,
    ):
        self._run_service = run_service
        self._run = run
        super().__init__(
            _stream_lines(run_service.stream_run(run, workflow)),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Analysis-Run-ID": str(run.id)},
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with CancelScope(shield=True):
                try:
                    await self.body_iterator.aclose()
                finally:
                    await run_in_threadpool(
                        self._run_service.cancel_if_active,
                        organization_id=self._run.organization_id,
                        run_id=self._run.id,
                    )


@router.post(BASE_PATH + "/stream")
def stream_competitive_analysis(
    payload: CompetitiveAnalysisRequest,
    access: AnalysisAccess,
    workflow: Workflow,
    run_service: RunService,
) -> StreamingResponse:
    context = access.organization_context
    run = run_service.create_run(
        organization_id=context.organization.id,
        requested_by_user_id=context.user.id,
        company_name=payload.company_name,
    )
    return AnalysisRunStreamingResponse(run_service, run, workflow)


@router.post(BASE_PATH, response_model=CompetitiveAnalysisResponse)
def run_competitive_analysis(
    payload: CompetitiveAnalysisRequest,
    access: AnalysisAccess,
    workflow: Workflow,
    run_service: RunService,
) -> CompetitiveAnalysisResponse:
    context = access.organization_context
    run = run_service.create_run(
        organization_id=context.organization.id,
        requested_by_user_id=context.user.id,
        company_name=payload.company_name,
    )
    try:
        result = run_service.execute(run, workflow)
    except service.AnalysisExecutionError as error:
        status_code = (
            422
            if error.code in {"invalid_company", "no_search_results"}
            else 500
            if error.code == "unexpected_error"
            else 502
        )
        raise HTTPException(
            status_code=status_code,
            detail=str(error),
            headers={"X-Analysis-Run-ID": str(run.id)},
        ) from error
    return CompetitiveAnalysisResponse(
        run_id=run.id,
        company_name=result.company_name,
        sector=result.sector,
        report=result.report,
    )


@router.get(BASE_PATH, response_model=AnalysisRunPage)
def list_competitive_analysis_runs(
    session: SessionDependency,
    access: AnalysisAccess,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AnalysisRunPage:
    return service.list_runs(
        session,
        organization_id=access.organization_context.organization.id,
        limit=limit,
        offset=offset,
    )


@router.get(BASE_PATH + "/{run_id}", response_model=AnalysisRunDetail)
def get_competitive_analysis_run(
    run_id: UUID,
    session: SessionDependency,
    access: AnalysisAccess,
) -> AnalysisRunDetail:
    try:
        return service.get_run(
            session,
            organization_id=access.organization_context.organization.id,
            run_id=run_id,
        )
    except service.AnalysisRunNotFoundError as error:
        raise HTTPException(status_code=404, detail="Analysis run not found") from error
