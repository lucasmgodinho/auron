import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.auth import service
from app.core.auth.dependencies import AUTH_SESSION_COOKIE_NAME
from app.core.auth.model import AuthIdentity, AuthSession
from app.core.users import service as user_service
from app.core.users.model import User


def create_user(
    session: Session,
    *,
    email: str = "lucas@example.com",
    name: str = "Lucas",
) -> User:
    return user_service.create_user(session, email=email, name=name)


def create_session(session: Session) -> tuple[User, AuthSession, str]:
    user = create_user(session)
    auth_session, raw_token = service.create_auth_session(session, user.id)
    return user, auth_session, raw_token


def set_session_cookie(client: TestClient, raw_token: str) -> None:
    client.cookies.set(AUTH_SESSION_COOKIE_NAME, raw_token)


def test_link_identity_to_existing_user(db_session: Session) -> None:
    user = create_user(db_session)

    identity = service.link_identity(
        db_session,
        user_id=user.id,
        provider="google",
        provider_subject="provider-user-123",
    )

    assert identity.user_id == user.id
    assert identity.provider == "google"
    assert identity.provider_subject == "provider-user-123"
    assert identity.created_at
    assert (
        service.find_user_by_external_identity(
            db_session,
            provider="google",
            provider_subject="provider-user-123",
        )
        == user
    )


def test_link_identity_normalizes_provider_and_surrounding_whitespace(
    db_session: Session,
) -> None:
    user = create_user(db_session)

    identity = service.link_identity(
        db_session,
        user_id=user.id,
        provider="  GOOGLE  ",
        provider_subject="  Subject-With-Case  ",
    )

    assert identity.provider == "google"
    assert identity.provider_subject == "Subject-With-Case"


@pytest.mark.parametrize("provider", ["", "   "])
def test_link_identity_rejects_empty_provider(
    db_session: Session, provider: str
) -> None:
    user = create_user(db_session)

    with pytest.raises(ValueError, match="Provider must contain"):
        service.link_identity(
            db_session,
            user_id=user.id,
            provider=provider,
            provider_subject="subject",
        )


@pytest.mark.parametrize("provider_subject", ["", "   "])
def test_link_identity_rejects_empty_provider_subject(
    db_session: Session, provider_subject: str
) -> None:
    user = create_user(db_session)

    with pytest.raises(ValueError, match="Provider subject must contain"):
        service.link_identity(
            db_session,
            user_id=user.id,
            provider="google",
            provider_subject=provider_subject,
        )


def test_link_identity_rejects_duplicate_provider_subject(db_session: Session) -> None:
    user = create_user(db_session)
    service.link_identity(
        db_session,
        user_id=user.id,
        provider="google",
        provider_subject="subject",
    )

    with pytest.raises(service.AuthIdentityConflictError):
        service.link_identity(
            db_session,
            user_id=user.id,
            provider="GOOGLE",
            provider_subject="subject",
        )


def test_duplicate_identity_cannot_move_to_another_user(db_session: Session) -> None:
    first_user = create_user(db_session, email="first@example.com", name="First")
    second_user = create_user(db_session, email="second@example.com", name="Second")
    service.link_identity(
        db_session,
        user_id=first_user.id,
        provider="google",
        provider_subject="subject",
    )

    with pytest.raises(service.AuthIdentityConflictError):
        service.link_identity(
            db_session,
            user_id=second_user.id,
            provider="google",
            provider_subject="subject",
        )

    resolved_user = service.find_user_by_external_identity(
        db_session, provider="google", provider_subject="subject"
    )
    assert resolved_user == first_user


def test_user_may_have_identities_from_different_providers(db_session: Session) -> None:
    user = create_user(db_session)

    google_identity = service.link_identity(
        db_session,
        user_id=user.id,
        provider="google",
        provider_subject="shared-subject",
    )
    microsoft_identity = service.link_identity(
        db_session,
        user_id=user.id,
        provider="microsoft",
        provider_subject="shared-subject",
    )

    assert google_identity.user_id == microsoft_identity.user_id == user.id


def test_link_identity_rejects_missing_user(db_session: Session) -> None:
    with pytest.raises(user_service.UserNotFoundError):
        service.link_identity(
            db_session,
            user_id=uuid4(),
            provider="google",
            provider_subject="subject",
        )


def test_identity_service_reraises_unrelated_integrity_error(
    db_session: Session,
) -> None:
    user = create_user(db_session)
    db_session.add(
        AuthIdentity(
            user_id=uuid4(),
            provider="microsoft",
            provider_subject="missing-user",
        )
    )

    with db_session.no_autoflush, pytest.raises(IntegrityError) as error:
        service.link_identity(
            db_session,
            user_id=user.id,
            provider="google",
            provider_subject="subject",
        )

    assert error.value.orig.sqlstate == "23503"


def test_create_session_for_existing_user(db_session: Session) -> None:
    user, auth_session, raw_token = create_session(db_session)

    assert auth_session.user_id == user.id
    assert raw_token
    assert auth_session.created_at


def test_raw_session_token_is_not_stored(db_session: Session) -> None:
    _, auth_session, raw_token = create_session(db_session)

    stored_session = db_session.get(AuthSession, auth_session.id)

    assert stored_session is not None
    assert stored_session.token_hash != raw_token
    assert not hasattr(stored_session, "raw_token")


def test_stored_session_token_hash_uses_sha256(db_session: Session) -> None:
    _, auth_session, raw_token = create_session(db_session)

    assert auth_session.token_hash == hashlib.sha256(raw_token.encode()).hexdigest()


def test_session_has_configured_expiration(db_session: Session) -> None:
    _, auth_session, _ = create_session(db_session)
    expected_lifetime = timedelta(hours=get_settings().auth_session_ttl_hours)

    assert auth_session.expires_at > auth_session.created_at
    assert expected_lifetime - timedelta(seconds=5) < (
        auth_session.expires_at - auth_session.created_at
    ) < expected_lifetime + timedelta(seconds=5)


def test_create_session_rejects_missing_user(db_session: Session) -> None:
    with pytest.raises(user_service.UserNotFoundError):
        service.create_auth_session(db_session, uuid4())


def test_auth_session_token_hash_is_unique(db_session: Session) -> None:
    user, auth_session, _ = create_session(db_session)
    db_session.add(
        AuthSession(
            user_id=user.id,
            token_hash=auth_session.token_hash,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )

    with pytest.raises(IntegrityError) as error:
        db_session.commit()
    db_session.rollback()

    assert isinstance(error.value.orig, UniqueViolation)
    assert error.value.orig.diag.constraint_name == "uq_auth_sessions_token_hash"


def test_auth_me_without_cookie_returns_unauthorized(client: TestClient) -> None:
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_auth_me_with_invalid_token_returns_unauthorized(client: TestClient) -> None:
    set_session_cookie(client, "invalid-token")

    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_auth_me_with_valid_session_returns_user(
    client: TestClient, db_session: Session
) -> None:
    user, _, raw_token = create_session(db_session)
    set_session_cookie(client, raw_token)

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json()["id"] == str(user.id)
    assert response.json()["email"] == user.email


def test_auth_me_rejects_expired_session(
    client: TestClient, db_session: Session
) -> None:
    _, auth_session, raw_token = create_session(db_session)
    auth_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    set_session_cookie(client, raw_token)

    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_auth_me_rejects_revoked_session(
    client: TestClient, db_session: Session
) -> None:
    _, auth_session, raw_token = create_session(db_session)
    auth_session.revoked_at = datetime.now(UTC)
    db_session.commit()
    set_session_cookie(client, raw_token)

    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_logout_revokes_session_clears_cookie_and_prevents_reuse(
    client: TestClient, db_session: Session
) -> None:
    _, auth_session, raw_token = create_session(db_session)
    set_session_cookie(client, raw_token)

    response = client.post("/auth/logout")

    db_session.refresh(auth_session)
    set_cookie = response.headers["set-cookie"].lower()
    assert response.status_code == 204
    assert auth_session.revoked_at is not None
    assert "platform_session=" in set_cookie
    assert "max-age=0" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie

    set_session_cookie(client, raw_token)
    reuse_response = client.get("/auth/me")
    assert reuse_response.status_code == 401


def assert_logout_cookie_is_cleared(response: Response) -> None:
    set_cookie = response.headers["set-cookie"].lower()
    assert response.status_code == 204
    assert "platform_session=" in set_cookie
    assert "max-age=0" in set_cookie
    assert "path=/" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie


def test_logout_with_expired_session_is_idempotent(
    client: TestClient, db_session: Session
) -> None:
    _, auth_session, raw_token = create_session(db_session)
    auth_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    set_session_cookie(client, raw_token)

    response = client.post("/auth/logout")

    assert_logout_cookie_is_cleared(response)
    assert client.get("/auth/me").status_code == 401


def test_logout_with_revoked_session_is_idempotent(
    client: TestClient, db_session: Session
) -> None:
    _, auth_session, raw_token = create_session(db_session)
    revoked_at = datetime.now(UTC)
    auth_session.revoked_at = revoked_at
    db_session.commit()
    set_session_cookie(client, raw_token)

    response = client.post("/auth/logout")

    assert_logout_cookie_is_cleared(response)
    db_session.refresh(auth_session)
    assert auth_session.revoked_at == revoked_at
    assert client.get("/auth/me").status_code == 401


def test_logout_with_unknown_token_is_idempotent(client: TestClient) -> None:
    set_session_cookie(client, "unknown-token")

    response = client.post("/auth/logout")

    assert_logout_cookie_is_cleared(response)
    assert client.get("/auth/me").status_code == 401


def test_logout_without_cookie_is_idempotent(client: TestClient) -> None:
    response = client.post("/auth/logout")

    assert_logout_cookie_is_cleared(response)
