import logging
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.application_events import repository
from app.core.application_events.context import get_application_event_context
from app.core.application_events.model import ApplicationEvent
from app.database import SessionLocal

logger = logging.getLogger(__name__)

EVENT_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
VALID_LEVELS = frozenset({"debug", "info", "warning", "error", "critical"})
VALID_CATEGORIES = frozenset(
    {"api", "auth", "access", "organization", "module", "business", "integration", "application"}
)
ALLOWED_METADATA_KEYS = frozenset(
    {
        "method",
        "route",
        "authentication_method",
        "module_key",
        "enabled",
        "previous_role",
        "new_role",
        "permission_count",
        "membership_count",
        "invitation_count",
        "provider",
        "attempt",
        "result_count",
    }
)
MAX_METADATA_ITEMS = 20
MAX_METADATA_STRING_LENGTH = 500


class InvalidApplicationEventError(ValueError):
    pass


def sanitize_metadata(
    metadata: Mapping[str, object] | None,
) -> dict[str, str | int | bool | None]:
    if not metadata:
        return {}
    sanitized: dict[str, str | int | bool | None] = {}
    for key in sorted(metadata):
        if key not in ALLOWED_METADATA_KEYS or len(sanitized) >= MAX_METADATA_ITEMS:
            continue
        value = metadata[key]
        if value is None or isinstance(value, bool) or isinstance(value, int):
            sanitized[key] = value
        elif isinstance(value, str):
            sanitized[key] = value[:MAX_METADATA_STRING_LENGTH]
    return sanitized


def _validate_event(level: str, event: str, category: str) -> None:
    if level not in VALID_LEVELS:
        raise InvalidApplicationEventError(f"Unsupported event level: {level}")
    if category not in VALID_CATEGORIES:
        raise InvalidApplicationEventError(f"Unsupported event category: {category}")
    if EVENT_PATTERN.fullmatch(event) is None or len(event) > 150:
        raise InvalidApplicationEventError(f"Invalid semantic event name: {event}")


def record_event(
    *,
    level: str,
    event: str,
    category: str,
    module: str | None = None,
    request_id: str | None = None,
    user_id: UUID | None = None,
    organization_id: UUID | None = None,
    resource_type: str | None = None,
    resource_id: UUID | str | None = None,
    status: str | None = None,
    duration_ms: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    metadata: Mapping[str, object] | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> bool:
    try:
        _validate_event(level, event, category)
        context = get_application_event_context()
        factory = session_factory or (context.session_factory if context else None) or SessionLocal
        application_event = ApplicationEvent(
            level=level,
            event=event,
            category=category,
            module=module[:100] if module else None,
            request_id=request_id or (context.request_id if context else None),
            user_id=user_id or (context.user_id if context else None),
            organization_id=organization_id or (context.organization_id if context else None),
            resource_type=resource_type[:100] if resource_type else None,
            resource_id=str(resource_id)[:255] if resource_id is not None else None,
            status=status[:50] if status else None,
            duration_ms=max(duration_ms, 0) if duration_ms is not None else None,
            error_code=error_code[:100] if error_code else None,
            error_message=error_message[:500] if error_message else None,
            event_metadata=sanitize_metadata(metadata),
        )
        with factory() as session:
            repository.add_event(session, application_event)
            session.commit()
        return True
    except Exception:
        logger.exception("Failed to persist application event %s", event)
        return False


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
    return repository.list_events(
        session,
        organization_id=organization_id,
        date_from=date_from,
        date_to=date_to,
        level=level,
        category=category,
        module=module,
        event_name=event_name,
        user_id=user_id,
        request_id=request_id,
        limit=limit,
        offset=offset,
    )


def get_event(
    session: Session,
    *,
    organization_id: UUID,
    event_id: UUID,
) -> ApplicationEvent | None:
    return repository.get_event(
        session,
        organization_id=organization_id,
        event_id=event_id,
    )
