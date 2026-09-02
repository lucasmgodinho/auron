from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.application_events import service
from app.core.application_events.model import ApplicationEvent
from app.core.application_events.schemas import (
    ApplicationEventPage,
    ApplicationEventResponse,
)
from app.core.organization_context.context import OrganizationContext
from app.core.organization_context.dependencies import get_organization_context
from app.core.users.model import User
from app.database import get_session

router = APIRouter(tags=["application events"])


def _event_response(
    event: ApplicationEvent,
    *,
    user_name: str | None,
    organization_name: str,
) -> ApplicationEventResponse:
    return ApplicationEventResponse.model_validate(event).model_copy(
        update={
            "user_name": user_name,
            "organization_name": organization_name,
        }
    )


def get_application_event_admin_context(
    context: Annotated[OrganizationContext, Depends(get_organization_context)],
) -> OrganizationContext:
    if context.membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return context


@router.get(
    "/organizations/{organization_id}/application-events",
    response_model=ApplicationEventPage,
)
def list_application_events(
    session: Annotated[Session, Depends(get_session)],
    context: Annotated[
        OrganizationContext,
        Depends(get_application_event_admin_context),
    ],
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    level: Literal["debug", "info", "warning", "error", "critical"] | None = None,
    category: str | None = Query(default=None, max_length=50),
    module: str | None = Query(default=None, max_length=100),
    event: str | None = Query(default=None, max_length=150),
    user_id: UUID | None = None,
    request_id: str | None = Query(default=None, max_length=128),
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApplicationEventPage:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from must be before date_to",
        )
    items, total = service.list_events(
        session,
        organization_id=context.organization.id,
        date_from=date_from,
        date_to=date_to,
        level=level,
        category=category,
        module=module,
        event_name=event,
        user_id=user_id,
        request_id=request_id,
        limit=limit,
        offset=offset,
    )
    user_ids = {item.user_id for item in items if item.user_id is not None}
    user_names = (
        dict(
            session.execute(
                select(User.id, User.name).where(User.id.in_(user_ids))
            ).tuples().all()
        )
        if user_ids
        else {}
    )
    return ApplicationEventPage(
        items=[
            _event_response(
                item,
                user_name=user_names.get(item.user_id),
                organization_name=context.organization.name,
            )
            for item in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/organizations/{organization_id}/application-events/{event_id}",
    response_model=ApplicationEventResponse,
)
def get_application_event(
    event_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    context: Annotated[
        OrganizationContext,
        Depends(get_application_event_admin_context),
    ],
) -> ApplicationEventResponse:
    event = service.get_event(
        session,
        organization_id=context.organization.id,
        event_id=event_id,
    )
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    user = session.get(User, event.user_id) if event.user_id is not None else None
    return _event_response(
        event,
        user_name=user.name if user is not None else None,
        organization_name=context.organization.name,
    )
