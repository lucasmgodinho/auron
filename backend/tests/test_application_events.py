from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.application_events.context import (
    begin_application_event_context,
    reset_application_event_context,
)
from app.core.application_events.model import ApplicationEvent
from app.core.application_events.service import record_event, sanitize_metadata
from app.core.auth import service as auth_service
from app.core.auth.dependencies import AUTH_SESSION_COOKIE_NAME
from app.core.organization_memberships import repository as membership_repository
from app.core.organizations import service as organization_service
from app.core.users import service as user_service
from app.core.users.model import User
from app.main import app


def create_user(session: Session, email: str, name: str = "Event User") -> User:
    return user_service.create_user(session, email=email, name=name)


def authenticate(client: TestClient, session: Session, user: User) -> None:
    _, raw_token = auth_service.create_auth_session(session, user.id)
    client.cookies.set(AUTH_SESSION_COOKIE_NAME, raw_token)


def event_session_factory(db_session: Session):
    def create_session() -> Session:
        return Session(
            bind=db_session.connection(),
            join_transaction_mode="create_savepoint",
        )

    return create_session


def test_record_event_uses_request_context_and_sanitizes_metadata(
    db_session: Session,
) -> None:
    user = create_user(db_session, "context-event@example.com", "Context User")
    organization = organization_service.create_organization(
        db_session,
        "Context Events",
        user.id,
    )
    request_id = "request-context-123"
    token = begin_application_event_context(
        request_id=request_id,
        session_factory=event_session_factory(db_session),
    )
    try:
        from app.core.application_events.context import (
            bind_application_event_organization,
            bind_application_event_user,
        )

        bind_application_event_user(user.id)
        bind_application_event_organization(organization.id)
        persisted = record_event(
            level="info",
            event="report.generation.completed",
            category="business",
            module="competitive_intelligence",
            status="succeeded",
            metadata={
                "result_count": 3,
                "provider": "tavily",
                "password": "must-not-be-stored",
                "authorization": "Bearer secret",
                "token": "must-not-be-stored",
                "nested": {"api_key": "must-not-be-stored"},
            },
        )
    finally:
        reset_application_event_context(token)

    assert persisted is True
    event = db_session.scalar(
        select(ApplicationEvent).where(ApplicationEvent.request_id == request_id)
    )
    assert event is not None
    assert event.user_id == user.id
    assert event.organization_id == organization.id
    assert event.event_metadata == {"provider": "tavily", "result_count": 3}


def test_metadata_allowlist_rejects_sensitive_and_complex_values() -> None:
    sanitized = sanitize_metadata(
        {
            "method": "POST",
            "route": "/organizations/123",
            "password": "secret",
            "cookie": "platform_session=secret",
            "api_key": "secret",
            "provider": ["not", "a", "scalar"],
        }
    )

    assert sanitized == {
        "method": "POST",
        "route": "/organizations/123",
    }


def test_record_event_failure_does_not_escape() -> None:
    def broken_session_factory() -> Session:
        raise RuntimeError("logging database unavailable")

    assert record_event(
        level="info",
        event="api.request.completed",
        category="api",
        session_factory=broken_session_factory,
    ) is False


def test_application_event_api_is_tenant_scoped_authorized_and_paginated(
    client: TestClient,
    db_session: Session,
) -> None:
    owner = create_user(db_session, "event-owner@example.com", "Event Owner")
    admin = create_user(db_session, "event-admin@example.com", "Event Admin")
    member = create_user(db_session, "event-member@example.com")
    outsider = create_user(db_session, "event-outsider@example.com")
    other_owner = create_user(db_session, "event-other-owner@example.com")
    organization = organization_service.create_organization(
        db_session,
        "Event Organization",
        owner.id,
    )
    other_organization = organization_service.create_organization(
        db_session,
        "Other Event Organization",
        other_owner.id,
    )
    for user, role in ((admin, "admin"), (member, "member")):
        membership_repository.create_membership(
            db_session,
            user_id=user.id,
            organization_id=organization.id,
            role=role,
        )

    now = datetime.now(UTC)
    first = ApplicationEvent(
        created_at=now - timedelta(minutes=2),
        level="info",
        event="report.generation.started",
        category="business",
        module="competitive_intelligence",
        request_id="request-first",
        user_id=owner.id,
        organization_id=organization.id,
        status="started",
        event_metadata={},
    )
    second = ApplicationEvent(
        created_at=now - timedelta(minutes=1),
        level="error",
        event="report.generation.failed",
        category="business",
        module="competitive_intelligence",
        request_id="request-second",
        user_id=owner.id,
        organization_id=organization.id,
        status="failed",
        event_metadata={},
    )
    other = ApplicationEvent(
        created_at=now,
        level="critical",
        event="application.error",
        category="application",
        request_id="request-other-tenant",
        user_id=other_owner.id,
        organization_id=other_organization.id,
        status="failed",
        event_metadata={},
    )
    db_session.add_all([first, second, other])
    db_session.commit()

    authenticate(client, db_session, owner)
    page = client.get(
        f"/organizations/{organization.id}/application-events",
        params={"limit": 1, "offset": 0},
    )
    assert page.status_code == 200
    assert page.json()["total"] == 2
    assert page.json()["items"][0]["id"] == str(second.id)
    assert page.json()["items"][0]["user_name"] == "Event Owner"
    filtered = client.get(
        f"/organizations/{organization.id}/application-events",
        params={
            "level": "error",
            "module": "competitive_intelligence",
            "user_id": str(owner.id),
            "request_id": "request-second",
        },
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["id"] == str(second.id)
    assert client.get(
        f"/organizations/{organization.id}/application-events/{other.id}"
    ).status_code == 404

    authenticate(client, db_session, admin)
    assert client.get(
        f"/organizations/{organization.id}/application-events"
    ).status_code == 200
    authenticate(client, db_session, member)
    assert client.get(
        f"/organizations/{organization.id}/application-events"
    ).status_code == 403
    authenticate(client, db_session, outsider)
    assert client.get(
        f"/organizations/{organization.id}/application-events"
    ).status_code == 403


def test_request_logging_associates_request_user_and_organization(
    client: TestClient,
    db_session: Session,
) -> None:
    owner = create_user(db_session, "request-event@example.com", "Request User")
    organization = organization_service.create_organization(
        db_session,
        "Request Event Organization",
        owner.id,
    )
    authenticate(client, db_session, owner)

    response = client.get(
        f"/organizations/{organization.id}",
        headers={"X-Request-ID": "trusted-request-id"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "trusted-request-id"
    event = db_session.scalar(
        select(ApplicationEvent).where(
            ApplicationEvent.request_id == "trusted-request-id",
            ApplicationEvent.event == "api.request.completed",
        )
    )
    assert event is not None
    assert event.user_id == owner.id
    assert event.organization_id == organization.id
    assert event.event_metadata == {
        "method": "GET",
        "route": "/organizations/{organization_id}",
    }


def test_failed_login_is_instrumented_without_sensitive_values(
    client: TestClient,
    db_session: Session,
) -> None:
    response = client.post(
        "/auth/login",
        headers={"X-Request-ID": "failed-login-request"},
        json={"email": "missing@example.com", "password": "do-not-log-this"},
    )

    assert response.status_code == 401
    event = db_session.scalar(
        select(ApplicationEvent).where(
            ApplicationEvent.request_id == "failed-login-request",
            ApplicationEvent.event == "auth.login.failed",
        )
    )
    assert event is not None
    assert event.error_code == "invalid_credentials"
    assert event.event_metadata == {"authentication_method": "password"}
    assert "do-not-log-this" not in repr(event.event_metadata)


def test_logging_failure_does_not_break_primary_request(
    client: TestClient,
    db_session: Session,
) -> None:
    owner = create_user(db_session, "fail-safe-event@example.com")
    organization = organization_service.create_organization(
        db_session,
        "Fail Safe Events",
        owner.id,
    )
    authenticate(client, db_session, owner)

    def broken_session_factory() -> Session:
        raise RuntimeError("logging database unavailable")

    previous_factory = app.state.application_event_session_factory
    app.state.application_event_session_factory = broken_session_factory
    try:
        response = client.get(f"/organizations/{organization.id}")
    finally:
        app.state.application_event_session_factory = previous_factory

    assert response.status_code == 200
    assert UUID(response.headers["X-Request-ID"])
