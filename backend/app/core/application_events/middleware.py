import re
from time import perf_counter
from uuid import uuid4

from fastapi import Request, Response
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.application_events.context import (
    begin_application_event_context,
    get_application_event_context,
    reset_application_event_context,
)
from app.core.application_events.service import record_event

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
EXCLUDED_ROUTE_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json"})


def get_or_create_request_id(request: Request) -> str:
    supplied = request.headers.get(REQUEST_ID_HEADER)
    if supplied is not None and REQUEST_ID_PATTERN.fullmatch(supplied):
        return supplied
    return str(uuid4())


def _request_level(status_code: int) -> str:
    if status_code >= 500:
        return "error"
    if status_code >= 400:
        return "warning"
    return "info"


def _should_log_request(request: Request, route_path: str | None) -> bool:
    return (
        request.method != "OPTIONS"
        and route_path is not None
        and route_path not in EXCLUDED_ROUTE_PATHS
        and "/application-events" not in route_path
    )


class ApplicationEventMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = get_or_create_request_id(request)
        request.state.request_id = request_id
        session_factory = getattr(
            request.app.state,
            "application_event_session_factory",
            None,
        )
        context_token = begin_application_event_context(
            request_id=request_id,
            session_factory=session_factory,
        )
        started_at = perf_counter()
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            route = request.scope.get("route")
            route_path = getattr(route, "path", None)
            if _should_log_request(request, route_path):
                duration_ms = round((perf_counter() - started_at) * 1000)
                await run_in_threadpool(
                    record_event,
                    level=_request_level(response.status_code),
                    event="api.request.completed",
                    category="api",
                    status=str(response.status_code),
                    duration_ms=duration_ms,
                    metadata={"method": request.method, "route": route_path},
                )
                if response.status_code == 403:
                    await run_in_threadpool(
                        record_event,
                        level="warning",
                        event="access.denied",
                        category="access",
                        status="denied",
                        metadata={"method": request.method, "route": route_path},
                    )
            return response
        finally:
            reset_application_event_context(context_token)


def get_request_context_request_id() -> str | None:
    context = get_application_event_context()
    return context.request_id if context is not None else None
