import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.auth import google, local
from app.core.auth import service as auth_service
from app.core.auth.dependencies import AUTH_SESSION_COOKIE_NAME
from app.core.auth.model import (
    AuthIdentity,
    AuthSession,
    EmailVerification,
    LocalCredential,
)
from app.core.email import smtp
from app.core.users import service as user_service
from app.core.users.model import User


@pytest.fixture
def sent_verifications(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(smtp, "ensure_email_delivery_configured", lambda: None)
    monkeypatch.setattr(
        smtp,
        "send_verification_email",
        lambda *, recipient, raw_token: sent.append((recipient, raw_token)),
    )
    return sent


def register(
    client: TestClient,
    *,
    email: str = "LOCAL@EXAMPLE.COM",
    name: str = "Local User",
) -> object:
    return client.post("/auth/register", json={"email": email, "name": name})


def test_local_registration_verification_login_and_session_flow(
    client: TestClient,
    db_session: Session,
    sent_verifications: list[tuple[str, str]],
) -> None:
    registration_response = register(client)

    user = db_session.scalar(select(User).where(User.email == "local@example.com"))
    assert registration_response.status_code == 202
    assert user is not None
    assert user.email_verified_at is None
    assert db_session.scalar(
        select(LocalCredential).where(LocalCredential.user_id == user.id)
    ) is None
    verification = db_session.scalar(
        select(EmailVerification).where(EmailVerification.user_id == user.id)
    )
    assert verification is not None
    assert sent_verifications[0][0] == user.email
    raw_token = sent_verifications[0][1]
    assert verification.token_hash == hashlib.sha256(raw_token.encode()).hexdigest()
    assert verification.token_hash != raw_token

    completion_response = client.post(
        "/auth/email-verifications/complete",
        json={"token": raw_token, "password": "correct horse battery staple"},
    )

    db_session.refresh(user)
    db_session.refresh(verification)
    credential = db_session.scalar(
        select(LocalCredential).where(LocalCredential.user_id == user.id)
    )
    assert completion_response.status_code == 200
    assert user.email_verified_at is not None
    assert verification.used_at is not None
    assert credential is not None
    assert credential.password_hash.startswith("$argon2id$")
    assert "correct horse battery staple" not in credential.password_hash
    assert local._PASSWORD_HASHER.verify(
        credential.password_hash, "correct horse battery staple"
    )
    assert db_session.scalar(
        select(func.count()).select_from(AuthSession).where(AuthSession.user_id == user.id)
    ) == 1
    assert client.cookies.get(AUTH_SESSION_COOKIE_NAME)
    assert client.get("/auth/me").json()["id"] == str(user.id)

    assert client.post("/auth/logout").status_code == 204
    login_response = client.post(
        "/auth/login",
        json={"email": " LOCAL@EXAMPLE.COM ", "password": "correct horse battery staple"},
    )
    assert login_response.status_code == 200
    assert login_response.json()["id"] == str(user.id)
    assert client.get("/auth/me").status_code == 200


def test_registration_of_google_only_user_requires_email_proof_and_reuses_user(
    client: TestClient,
    db_session: Session,
    sent_verifications: list[tuple[str, str]],
) -> None:
    user = user_service.create_user(
        db_session, email="victim@example.com", name="Existing Google Name"
    )
    user.email_verified_at = datetime.now(UTC)
    db_session.commit()
    auth_service.link_identity(
        db_session,
        user_id=user.id,
        provider="google",
        provider_subject="victim-google-subject",
    )

    response = register(client, email="VICTIM@example.com", name="Attacker Name")

    db_session.refresh(user)
    assert response.status_code == 202
    assert user.name == "Existing Google Name"
    assert db_session.scalar(select(func.count()).select_from(User)) == 1
    assert db_session.scalar(
        select(LocalCredential).where(LocalCredential.user_id == user.id)
    ) is None
    assert db_session.scalar(
        select(EmailVerification).where(EmailVerification.user_id == user.id)
    ) is not None
    assert sent_verifications[0][0] == user.email

    completion = client.post(
        "/auth/email-verifications/complete",
        json={
            "token": sent_verifications[0][1],
            "password": "google and local password",
        },
    )
    assert completion.status_code == 200
    credential = db_session.scalar(
        select(LocalCredential).where(LocalCredential.user_id == user.id)
    )
    assert credential is not None
    assert credential.user_id == user.id
    assert db_session.scalar(select(func.count()).select_from(User)) == 1


def test_registration_does_not_replace_existing_local_credential(
    client: TestClient,
    db_session: Session,
    sent_verifications: list[tuple[str, str]],
) -> None:
    user = user_service.create_user(
        db_session, email="existing-local@example.com", name="Existing Local"
    )
    user.email_verified_at = datetime.now(UTC)
    credential = LocalCredential(
        user_id=user.id,
        password_hash=local.hash_password("existing secure password"),
    )
    db_session.add(credential)
    db_session.commit()
    original_hash = credential.password_hash

    response = register(
        client,
        email=user.email,
        name="Attempted Replacement",
    )

    db_session.refresh(user)
    db_session.refresh(credential)
    assert response.status_code == 202
    assert credential.password_hash == original_hash
    assert user.name == "Existing Local"
    assert db_session.scalar(select(func.count()).select_from(User)) == 1
    assert db_session.scalar(select(func.count()).select_from(LocalCredential)) == 1
    assert db_session.scalar(select(func.count()).select_from(EmailVerification)) == 0
    assert sent_verifications == []


def test_registration_response_does_not_reveal_account_state(
    client: TestClient,
    db_session: Session,
    sent_verifications: list[tuple[str, str]],
) -> None:
    new_response = register(client, email="new@example.com")
    existing = user_service.create_user(
        db_session, email="credential@example.com", name="Credential"
    )
    existing.email_verified_at = datetime.now(UTC)
    db_session.add(
        LocalCredential(
            user_id=existing.id,
            password_hash=local.hash_password("existing secure password"),
        )
    )
    db_session.commit()

    existing_response = register(client, email=existing.email)

    assert new_response.status_code == existing_response.status_code == 202
    assert new_response.json() == existing_response.json()


def test_registration_rejects_malformed_email_without_creating_user(
    client: TestClient,
    db_session: Session,
    sent_verifications: list[tuple[str, str]],
) -> None:
    response = register(client, email="not-an-email")

    assert response.status_code == 422
    assert db_session.scalar(select(func.count()).select_from(User)) == 0


def test_verification_rejects_invalid_expired_used_and_short_password(
    client: TestClient,
    db_session: Session,
    sent_verifications: list[tuple[str, str]],
) -> None:
    register(client, email="verify-errors@example.com")
    raw_token = sent_verifications[0][1]
    verification = db_session.scalar(select(EmailVerification))
    assert verification is not None

    invalid = client.post(
        "/auth/email-verifications/complete",
        json={"token": "unknown", "password": "long enough password"},
    )
    short = client.post(
        "/auth/email-verifications/complete",
        json={"token": raw_token, "password": "short"},
    )
    verification.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    expired = client.post(
        "/auth/email-verifications/complete",
        json={"token": raw_token, "password": "long enough password"},
    )

    assert invalid.status_code == 400
    assert short.status_code == 422
    assert expired.status_code == 410
    assert db_session.scalar(select(func.count()).select_from(LocalCredential)) == 0

    verification.expires_at = datetime.now(UTC) + timedelta(hours=1)
    db_session.commit()
    assert client.post(
        "/auth/email-verifications/complete",
        json={"token": raw_token, "password": "long enough password"},
    ).status_code == 200
    used = client.post(
        "/auth/email-verifications/complete",
        json={"token": raw_token, "password": "another long password"},
    )
    assert used.status_code == 409
    assert db_session.scalar(select(func.count()).select_from(LocalCredential)) == 1


def test_resend_cooldown_and_rotation_invalidate_old_token(
    client: TestClient,
    db_session: Session,
    sent_verifications: list[tuple[str, str]],
) -> None:
    register(client, email="resend@example.com")
    old_token = sent_verifications[0][1]

    cooldown_response = client.post(
        "/auth/email-verifications/resend", json={"email": "resend@example.com"}
    )
    assert cooldown_response.status_code == 202
    assert len(sent_verifications) == 1

    verification = db_session.scalar(select(EmailVerification))
    assert verification is not None
    verification.last_sent_at = datetime.now(UTC) - timedelta(minutes=2)
    db_session.commit()
    resend_response = client.post(
        "/auth/email-verifications/resend", json={"email": "RESEND@example.com"}
    )
    new_token = sent_verifications[-1][1]

    assert resend_response.status_code == 202
    assert new_token != old_token
    assert client.post(
        "/auth/email-verifications/complete",
        json={"token": old_token, "password": "long enough password"},
    ).status_code == 400


def test_smtp_failure_leaves_challenge_and_resend_can_recover(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smtp, "ensure_email_delivery_configured", lambda: None)

    def fail_delivery(**_kwargs: str) -> None:
        raise smtp.EmailDeliveryError

    monkeypatch.setattr(smtp, "send_verification_email", fail_delivery)
    response = register(client, email="delivery-failure@example.com")

    verification = db_session.scalar(select(EmailVerification))
    assert response.status_code == 503
    assert verification is not None
    verification.last_sent_at = datetime.now(UTC) - timedelta(minutes=2)
    db_session.commit()

    delivered: list[str] = []
    monkeypatch.setattr(
        smtp,
        "send_verification_email",
        lambda *, recipient, raw_token: delivered.append(f"{recipient}:{raw_token}"),
    )
    resend_response = client.post(
        "/auth/email-verifications/resend",
        json={"email": "delivery-failure@example.com"},
    )
    assert resend_response.status_code == 202
    assert len(delivered) == 1


def test_registration_commits_before_smtp_delivery(
    test_engine: Engine,
) -> None:
    email = f"transaction-boundary-{uuid4().hex}@example.com"
    try:
        with Session(test_engine) as session:
            delivery = local.register(session, email=email, name="Transaction Boundary")
            assert delivery is not None
            assert session.in_transaction() is False
    finally:
        _cleanup_local_user(test_engine, email)


def test_email_endpoints_are_optional_but_fail_safely_when_unconfigured(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smtp, "ensure_email_delivery_configured", lambda: (_ for _ in ()).throw(
        smtp.EmailDeliveryNotConfiguredError()
    ))

    register_response = register(client, email="unconfigured@example.com")
    resend_response = client.post(
        "/auth/email-verifications/resend",
        json={"email": "unconfigured@example.com"},
    )
    assert register_response.status_code == resend_response.status_code == 503


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("unknown@example.com", "long enough password"),
        ("google-only@example.com", "long enough password"),
        ("local-login@example.com", "wrong password value"),
    ],
)
def test_invalid_logins_use_same_generic_response(
    client: TestClient,
    db_session: Session,
    email: str,
    password: str,
) -> None:
    google_user = user_service.create_user(
        db_session, email="google-only@example.com", name="Google Only"
    )
    google_user.email_verified_at = datetime.now(UTC)
    local_user = user_service.create_user(
        db_session, email="local-login@example.com", name="Local"
    )
    local_user.email_verified_at = datetime.now(UTC)
    db_session.add(
        LocalCredential(
            user_id=local_user.id,
            password_hash=local.hash_password("correct local password"),
        )
    )
    db_session.commit()

    response = client.post("/auth/login", json={"email": email, "password": password})

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password."}


def test_missing_credential_uses_dummy_argon_verification(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    verified_hashes: list[str] = []

    def capture_verification(password_hash: str, _password: str) -> bool:
        verified_hashes.append(password_hash)
        return False

    monkeypatch.setattr(local, "_verify_password", capture_verification)

    with pytest.raises(local.InvalidCredentialsError):
        local.login(
            db_session,
            email="missing@example.com",
            password="long enough password",
        )

    assert verified_hashes == [local._DUMMY_PASSWORD_HASH]


def test_successful_login_rehashes_outdated_argon_parameters(
    db_session: Session,
) -> None:
    user = user_service.create_user(
        db_session, email="rehash@example.com", name="Rehash"
    )
    user.email_verified_at = datetime.now(UTC)
    old_hash = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(
        "rehash secure password"
    )
    credential = LocalCredential(user_id=user.id, password_hash=old_hash)
    db_session.add(credential)
    db_session.commit()

    resolved_user, _ = local.login(
        db_session,
        email=user.email,
        password="rehash secure password",
    )

    db_session.refresh(credential)
    assert resolved_user.id == user.id
    assert credential.password_hash != old_hash
    assert local._PASSWORD_HASHER.verify(
        credential.password_hash, "rehash secure password"
    )


def test_local_user_first_google_link_reuses_same_user_and_credential(
    db_session: Session,
) -> None:
    user = user_service.create_user(
        db_session, email="local-then-google@example.com", name="Local First"
    )
    user.email_verified_at = datetime.now(UTC)
    credential = LocalCredential(
        user_id=user.id,
        password_hash=local.hash_password("local then google password"),
    )
    db_session.add(credential)
    db_session.commit()

    google_user = google.resolve_google_user(
        db_session,
        {
            "sub": "local-then-google-subject",
            "email": "LOCAL-THEN-GOOGLE@example.com",
            "email_verified": True,
            "name": "Google Name",
        },
    )

    assert google_user.id == user.id
    assert db_session.scalar(select(func.count()).select_from(User)) == 1
    identity = db_session.scalar(select(AuthIdentity))
    assert identity is not None
    assert identity.user_id == user.id
    assert db_session.get(LocalCredential, credential.id) is not None


def test_smtp_message_uses_fragment_and_expected_recipient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[object] = []

    class FakeSmtp:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> FakeSmtp:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def send_message(self, message: object) -> None:
            messages.append(message)

    monkeypatch.setattr(
        smtp,
        "get_settings",
        lambda: SimpleNamespace(
            email_delivery_configured=True,
            smtp_host="127.0.0.1",
            smtp_port=1025,
            smtp_starttls=False,
            smtp_username=None,
            smtp_password=None,
            email_from="no-reply@auron.test",
            frontend_base_url="http://127.0.0.1:5173/",
            email_verification_ttl_hours=24,
        ),
    )
    monkeypatch.setattr(smtp.smtplib, "SMTP", FakeSmtp)

    smtp.send_verification_email(
        recipient="recipient@example.com", raw_token="raw-token-value"
    )

    assert len(messages) == 1
    message = messages[0]
    assert message["To"] == "recipient@example.com"
    body = message.get_content()
    assert "/verify-email#token=raw-token-value" in body
    assert "/verify-email?token=" not in body


def test_concurrent_registration_creates_one_user_and_verification(
    test_engine: Engine,
) -> None:
    suffix = uuid4().hex
    email = f"concurrent-register-{suffix}@example.com"
    start = Barrier(2)

    def register_once() -> str:
        with Session(test_engine) as session:
            start.wait(timeout=10)
            delivery = local.register(session, email=email, name="Concurrent")
            return "send" if delivery is not None else "cooldown"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [future.result(timeout=20) for future in [
                executor.submit(register_once), executor.submit(register_once)
            ]]
        with Session(test_engine) as session:
            user_count = session.scalar(
                select(func.count()).select_from(User).where(User.email == email)
            )
            verification_count = session.scalar(
                select(func.count())
                .select_from(EmailVerification)
                .join(User, User.id == EmailVerification.user_id)
                .where(User.email == email)
            )
        assert sorted(results) == ["cooldown", "send"]
        assert user_count == verification_count == 1
    finally:
        _cleanup_local_user(test_engine, email)


def test_concurrent_google_and_registration_converge_on_one_user(
    test_engine: Engine,
) -> None:
    suffix = uuid4().hex
    email = f"concurrent-convergence-{suffix}@example.com"
    subject = f"google-{suffix}"
    start = Barrier(2)

    def register_once() -> UUID:
        with Session(test_engine) as session:
            start.wait(timeout=10)
            local.register(session, email=email, name="Local Name")
            user = session.scalar(select(User).where(User.email == email))
            assert user is not None
            return user.id

    def google_once() -> UUID:
        with Session(test_engine) as session:
            start.wait(timeout=10)
            return google.resolve_google_user(
                session,
                {
                    "sub": subject,
                    "email": email,
                    "email_verified": True,
                    "name": "Google Name",
                },
            ).id

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(register_once), executor.submit(google_once)]
            user_ids = [future.result(timeout=20) for future in futures]
        with Session(test_engine) as session:
            users = list(session.scalars(select(User).where(User.email == email)))
            identity = session.scalar(
                select(AuthIdentity).where(
                    AuthIdentity.provider == "google",
                    AuthIdentity.provider_subject == subject,
                )
            )
        assert len(users) == 1
        assert len(set(user_ids)) == 1
        assert identity is not None
        assert identity.user_id == users[0].id
        assert users[0].email_verified_at is not None
    finally:
        _cleanup_local_user(test_engine, email)


def test_concurrent_verification_completion_creates_one_credential_and_session(
    test_engine: Engine,
) -> None:
    suffix = uuid4().hex
    email = f"concurrent-completion-{suffix}@example.com"
    with Session(test_engine) as setup_session:
        delivery = local.register(setup_session, email=email, name="Concurrent")
        assert delivery is not None
        raw_token = delivery.raw_token
    start = Barrier(2)

    def complete_once() -> str:
        with Session(test_engine) as session:
            start.wait(timeout=10)
            try:
                local.complete_verification(
                    session,
                    raw_token=raw_token,
                    password="concurrent secure password",
                )
            except local.CompletedVerificationError:
                return "completed-before"
            return "completed"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [future.result(timeout=30) for future in [
                executor.submit(complete_once), executor.submit(complete_once)
            ]]
        with Session(test_engine) as session:
            user = session.scalar(select(User).where(User.email == email))
            assert user is not None
            credential_count = session.scalar(
                select(func.count())
                .select_from(LocalCredential)
                .where(LocalCredential.user_id == user.id)
            )
            session_count = session.scalar(
                select(func.count())
                .select_from(AuthSession)
                .where(AuthSession.user_id == user.id)
            )
        assert sorted(results) == ["completed", "completed-before"]
        assert credential_count == session_count == 1
    finally:
        _cleanup_local_user(test_engine, email)


def _cleanup_local_user(test_engine: Engine, email: str) -> None:
    with Session(test_engine) as session:
        user = session.scalar(select(User).where(User.email == email))
        if user is not None:
            session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
            session.execute(delete(AuthIdentity).where(AuthIdentity.user_id == user.id))
            session.execute(
                delete(EmailVerification).where(EmailVerification.user_id == user.id)
            )
            session.execute(
                delete(LocalCredential).where(LocalCredential.user_id == user.id)
            )
            session.delete(user)
            session.commit()
