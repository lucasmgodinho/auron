from collections.abc import Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session


@dataclass(slots=True)
class ApplicationEventContext:
    request_id: str | None = None
    user_id: UUID | None = None
    organization_id: UUID | None = None
    session_factory: Callable[[], Session] | None = None


_current_context: ContextVar[ApplicationEventContext | None] = ContextVar(
    "application_event_context",
    default=None,
)


def begin_application_event_context(
    *,
    request_id: str,
    session_factory: Callable[[], Session] | None,
) -> Token[ApplicationEventContext | None]:
    return _current_context.set(
        ApplicationEventContext(
            request_id=request_id,
            session_factory=session_factory,
        )
    )


def reset_application_event_context(
    token: Token[ApplicationEventContext | None],
) -> None:
    _current_context.reset(token)


def get_application_event_context() -> ApplicationEventContext | None:
    return _current_context.get()


def bind_application_event_user(user_id: UUID) -> None:
    context = _current_context.get()
    if context is not None:
        context.user_id = user_id


def bind_application_event_organization(organization_id: UUID) -> None:
    context = _current_context.get()
    if context is not None:
        context.organization_id = organization_id
