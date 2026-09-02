from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.application_events.model import ApplicationEvent


def add_event(session: Session, event: ApplicationEvent) -> ApplicationEvent:
    session.add(event)
    session.flush()
    return event


def _apply_filters(
    statement: Select[tuple[ApplicationEvent]],
    *,
    organization_id: UUID,
    date_from: datetime | None,
    date_to: datetime | None,
    level: str | None,
    category: str | None,
    module: str | None,
    event_name: str | None,
    user_id: UUID | None,
    request_id: str | None,
) -> Select[tuple[ApplicationEvent]]:
    statement = statement.where(ApplicationEvent.organization_id == organization_id)
    if date_from is not None:
        statement = statement.where(ApplicationEvent.created_at >= date_from)
    if date_to is not None:
        statement = statement.where(ApplicationEvent.created_at <= date_to)
    if level is not None:
        statement = statement.where(ApplicationEvent.level == level)
    if category is not None:
        statement = statement.where(ApplicationEvent.category == category)
    if module is not None:
        statement = statement.where(ApplicationEvent.module == module)
    if event_name is not None:
        statement = statement.where(ApplicationEvent.event == event_name)
    if user_id is not None:
        statement = statement.where(ApplicationEvent.user_id == user_id)
    if request_id is not None:
        statement = statement.where(ApplicationEvent.request_id == request_id)
    return statement


def list_events(
    session: Session,
    *,
    organization_id: UUID,
    date_from: datetime | None,
    date_to: datetime | None,
    level: str | None,
    category: str | None,
    module: str | None,
    event_name: str | None,
    user_id: UUID | None,
    request_id: str | None,
    limit: int,
    offset: int,
) -> tuple[list[ApplicationEvent], int]:
    filtered = _apply_filters(
        select(ApplicationEvent),
        organization_id=organization_id,
        date_from=date_from,
        date_to=date_to,
        level=level,
        category=category,
        module=module,
        event_name=event_name,
        user_id=user_id,
        request_id=request_id,
    )
    count_statement = filtered.with_only_columns(
        func.count(), maintain_column_froms=True
    ).order_by(None)
    total = session.scalar(count_statement) or 0
    items = list(
        session.scalars(
            filtered.order_by(
                ApplicationEvent.created_at.desc(),
                ApplicationEvent.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    )
    return items, total


def get_event(
    session: Session,
    *,
    organization_id: UUID,
    event_id: UUID,
) -> ApplicationEvent | None:
    return session.scalar(
        select(ApplicationEvent).where(
            ApplicationEvent.id == event_id,
            ApplicationEvent.organization_id == organization_id,
        )
    )
