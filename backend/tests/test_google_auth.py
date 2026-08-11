import hashlib
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from authlib.integrations.base_client import OAuthError
from authlib.oidc.core import UserInfo
from fastapi import Response
from fastapi.testclient import TestClient
from joserfc.errors import InvalidClaimError
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.auth import dependencies, google, service
from app.core.auth.model import AuthIdentity, AuthSession
from app.core.users import service as user_service
from app.core.users.model import User


def row_count(session: Session, model: type[User | AuthIdentity | AuthSession]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def google_claims(
    *,
    subject: str = "google-user-123",
    email: str = "lucas@example.com",
    email_verified: bool = True,
    name: object = "Lucas",
) -> dict[str, object]:
    return {
        "sub": subject,
        "email": email,
        "email_verified": email_verified,
        "name": name,
    }


def mock_google_callback(
    monkeypatch: pytest.MonkeyPatch,
    *,
    claims: Mapping[str, object],
) -> None:
    async def authorize_access_token(_request: object) -> dict[str, object]:
        return {
            "access_token": "google-access-token",
            "id_token": "google-id-token",
            "userinfo": UserInfo(dict(claims)),
        }

    monkeypatch.setattr(
        google.google_oauth_client,
        "authorize_access_token",
        authorize_access_token,
    )


def callback(client: TestClient) -> object:
    return client.get(
        "/auth/google/callback?code=google-authorization-code&state=state",
        follow_redirects=False,
    )


def test_google_login_uses_configured_redirect_and_library_state_and_nonce(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    async def load_server_metadata() -> dict[str, str]:
        return {"authorization_endpoint": "https://accounts.google.test/o/oauth2/auth"}

    monkeypatch.setattr(
        google.google_oauth_client,
        "load_server_metadata",
        load_server_metadata,
    )

    response = client.get(
        "/auth/google/login?redirect_uri=https://attacker.example/callback",
        follow_redirects=False,
    )

    assert response.status_code == 302
    authorization_url = urlparse(response.headers["location"])
    parameters = parse_qs(authorization_url.query)
    assert authorization_url.netloc == "accounts.google.test"
    assert parameters["redirect_uri"] == ["http://testserver/auth/google/callback"]
    assert set(parameters["scope"][0].split()) == {"openid", "email", "profile"}
    assert parameters["state"][0]
    assert parameters["nonce"][0]

    state_cookie = response.headers["set-cookie"].lower()
    assert "oauth_state=" in state_cookie
    assert "httponly" in state_cookie
    assert "samesite=lax" in state_cookie
    assert "max-age=600" in state_cookie
    assert "path=/auth/google" in state_cookie
    assert row_count(db_session, AuthSession) == 0


def test_first_google_login_creates_user_identity_and_platform_session(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    mock_google_callback(monkeypatch, claims=google_claims())

    response = callback(client)

    assert response.status_code == 302
    assert response.headers["location"] == "http://frontend.test/app"
    user = db_session.scalar(select(User))
    identity = db_session.scalar(select(AuthIdentity))
    auth_session = db_session.scalar(select(AuthSession))
    assert user is not None
    assert identity is not None
    assert auth_session is not None
    assert user.email == "lucas@example.com"
    assert user.name == "Lucas"
    assert identity.user_id == user.id
    assert identity.provider == "google"
    assert identity.provider_subject == "google-user-123"
    assert auth_session.user_id == user.id

    raw_session_token = client.cookies.get(dependencies.AUTH_SESSION_COOKIE_NAME)
    assert raw_session_token is not None
    assert auth_session.token_hash == hashlib.sha256(raw_session_token.encode()).hexdigest()
    session_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in session_cookie
    assert "samesite=lax" in session_cookie
    assert "path=/" in session_cookie
    assert "google-access-token" not in response.headers["location"]
    assert "google-id-token" not in response.headers["location"]
    assert "google-authorization-code" not in response.headers["location"]


@pytest.mark.parametrize("name", [None, "   ", "x" * 256])
def test_first_google_login_uses_email_when_name_is_unusable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    name: object,
) -> None:
    mock_google_callback(
        monkeypatch,
        claims=google_claims(email="FALLBACK@EXAMPLE.COM", name=name),
    )

    response = callback(client)

    assert response.status_code == 302
    user = db_session.scalar(select(User))
    assert user is not None
    assert user.email == "fallback@example.com"
    assert user.name == "fallback@example.com"


def test_google_login_links_existing_user_by_normalized_verified_email(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    user = user_service.create_user(
        db_session,
        email="existing@example.com",
        name="Existing name",
    )
    mock_google_callback(
        monkeypatch,
        claims=google_claims(email="  EXISTING@EXAMPLE.COM  ", name="Google name"),
    )

    response = callback(client)

    assert response.status_code == 302
    db_session.refresh(user)
    identity = db_session.scalar(select(AuthIdentity))
    assert row_count(db_session, User) == 1
    assert identity is not None
    assert identity.user_id == user.id
    assert user.name == "Existing name"


def test_existing_identity_wins_over_changed_email_and_does_not_reassign_user(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    identity_user = user_service.create_user(
        db_session,
        email="original@example.com",
        name="Original",
    )
    email_user = user_service.create_user(
        db_session,
        email="changed@example.com",
        name="Other user",
    )
    service.link_identity(
        db_session,
        user_id=identity_user.id,
        provider="google",
        provider_subject="stable-subject",
    )
    mock_google_callback(
        monkeypatch,
        claims=google_claims(
            subject="stable-subject",
            email=email_user.email,
            name="Changed Google name",
        ),
    )

    response = callback(client)

    assert response.status_code == 302
    raw_session_token = client.cookies.get(dependencies.AUTH_SESSION_COOKIE_NAME)
    assert raw_session_token is not None
    assert service.resolve_user_from_session_token(db_session, raw_session_token) == identity_user
    db_session.refresh(identity_user)
    assert identity_user.email == "original@example.com"
    assert identity_user.name == "Original"
    assert row_count(db_session, User) == 2
    assert row_count(db_session, AuthIdentity) == 1


def test_duplicate_google_callbacks_do_not_duplicate_user_or_identity(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    claims = google_claims()
    mock_google_callback(monkeypatch, claims=claims)
    first_response = callback(client)
    mock_google_callback(monkeypatch, claims=claims)
    second_response = callback(client)

    assert first_response.status_code == second_response.status_code == 302
    assert row_count(db_session, User) == 1
    assert row_count(db_session, AuthIdentity) == 1
    assert row_count(db_session, AuthSession) == 2


def test_concurrent_first_login_resolves_to_one_user_and_identity(
    test_engine: Engine,
) -> None:
    email = "concurrent-google-login@example.com"
    subject = "concurrent-google-subject"
    claims = google_claims(subject=subject, email=email)
    start = Barrier(2)

    def resolve_user_id() -> object:
        with Session(test_engine) as session:
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            session.execute(text("SELECT 1"))
            start.wait()
            return google.resolve_google_user(session, claims).id

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            user_ids = list(executor.map(lambda _index: resolve_user_id(), range(2)))

        with Session(test_engine) as verification_session:
            user_count = verification_session.scalar(
                select(func.count()).select_from(User).where(User.email == email)
            )
            identity_count = verification_session.scalar(
                select(func.count())
                .select_from(AuthIdentity)
                .where(
                    AuthIdentity.provider == "google",
                    AuthIdentity.provider_subject == subject,
                )
            )
        assert len(set(user_ids)) == 1
        assert user_count == 1
        assert identity_count == 1
    finally:
        with Session(test_engine) as cleanup_session:
            cleanup_session.execute(
                delete(AuthIdentity).where(
                    AuthIdentity.provider == "google",
                    AuthIdentity.provider_subject == subject,
                )
            )
            cleanup_session.execute(delete(User).where(User.email == email))
            cleanup_session.commit()


@pytest.mark.parametrize(
    "claims",
    [
        {"email": "lucas@example.com", "email_verified": True},
        {"sub": "subject", "email_verified": True},
        {"sub": "subject", "email": "lucas@example.com", "email_verified": False},
        {"sub": "subject", "email": "lucas@example.com"},
        {"sub": "subject", "email": "not-an-email", "email_verified": True},
    ],
    ids=[
        "missing-sub",
        "missing-email",
        "unverified-email",
        "missing-verification",
        "invalid-email",
    ],
)
def test_invalid_google_claims_fail_without_creating_rows(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    claims: Mapping[str, object],
) -> None:
    mock_google_callback(monkeypatch, claims=claims)

    response = callback(client)

    assert response.status_code == 401
    assert response.json() == {"detail": "Google authentication failed"}
    assert row_count(db_session, User) == 0
    assert row_count(db_session, AuthIdentity) == 0
    assert row_count(db_session, AuthSession) == 0


@pytest.mark.parametrize(
    "oidc_error",
    [
        OAuthError(error="access_denied"),
        InvalidClaimError("nonce"),
    ],
    ids=["provider-error", "invalid-nonce"],
)
def test_oidc_errors_are_generic_and_do_not_create_rows(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    oidc_error: Exception,
) -> None:
    async def authorize_access_token(_request: object) -> dict[str, object]:
        raise oidc_error

    monkeypatch.setattr(
        google.google_oauth_client,
        "authorize_access_token",
        authorize_access_token,
    )

    response = callback(client)

    assert response.status_code == 401
    assert response.json() == {"detail": "Google authentication failed"}
    assert "access_denied" not in response.text
    assert "state" not in response.text
    assert "nonce" not in response.text
    assert row_count(db_session, User) == 0
    assert row_count(db_session, AuthIdentity) == 0
    assert row_count(db_session, AuthSession) == 0


@pytest.mark.parametrize(
    "callback_url",
    [
        "/auth/google/callback?code=google-authorization-code",
        "/auth/google/callback?code=google-authorization-code&state=wrong-state",
    ],
    ids=["missing-state", "mismatched-state"],
)
def test_authlib_rejects_invalid_state_before_token_exchange(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    callback_url: str,
) -> None:
    async def load_server_metadata() -> dict[str, str]:
        return {"authorization_endpoint": "https://accounts.google.test/o/oauth2/auth"}

    monkeypatch.setattr(
        google.google_oauth_client,
        "load_server_metadata",
        load_server_metadata,
    )
    login_response = client.get("/auth/google/login", follow_redirects=False)
    assert login_response.status_code == 302

    response = client.get(callback_url, follow_redirects=False)

    assert response.status_code == 401
    assert response.json() == {"detail": "Google authentication failed"}
    assert row_count(db_session, User) == 0
    assert row_count(db_session, AuthIdentity) == 0
    assert row_count(db_session, AuthSession) == 0


def test_google_provider_tokens_are_not_persisted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    mock_google_callback(monkeypatch, claims=google_claims())

    response = callback(client)

    assert response.status_code == 302
    user = db_session.scalar(select(User))
    identity = db_session.scalar(select(AuthIdentity))
    auth_session = db_session.scalar(select(AuthSession))
    assert user is not None
    assert identity is not None
    assert auth_session is not None
    stored_values = " ".join(
        [
            user.email,
            user.name,
            identity.provider,
            identity.provider_subject,
            auth_session.token_hash,
        ]
    )
    assert "google-access-token" not in stored_values
    assert "google-id-token" not in stored_values
    assert "google-authorization-code" not in stored_values


def test_platform_session_cookie_is_secure_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: SimpleNamespace(
            auth_session_ttl_hours=168,
            auth_session_cookie_secure=True,
        ),
    )
    response = Response()

    dependencies.set_auth_session_cookie(response, "raw-token")

    set_cookie = response.headers["set-cookie"].lower()
    assert "secure" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
