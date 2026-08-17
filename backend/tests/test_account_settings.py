import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.auth import local
from app.core.auth import repository as auth_repository
from app.core.auth import service as auth_service
from app.core.auth.dependencies import AUTH_SESSION_COOKIE_NAME
from app.core.auth.model import (
    AuthIdentity,
    AuthSession,
    EmailVerification,
    LocalCredential,
)
from app.core.email import smtp
from app.core.organization_memberships.model import OrganizationMembership
from app.core.organizations import service as organization_service
from app.core.platform_admin.model import PlatformAdmin
from app.core.users import service as user_service
from app.core.users.model import User


def create_user(
    session: Session,
    *,
    email: str = "account@example.com",
    name: str = "Account User",
    verified: bool = True,
) -> User:
    user = user_service.create_user(session, email=email, name=name)
    if verified:
        user.email_verified_at = datetime.now(UTC)
        session.commit()
    return user


def add_password(session: Session, user: User, password: str) -> LocalCredential:
    credential = LocalCredential(
        user_id=user.id,
        password_hash=local.hash_password(password),
    )
    session.add(credential)
    session.commit()
    return credential


def authenticate(
    client: TestClient, session: Session, user: User
) -> tuple[AuthSession, str]:
    auth_session, raw_token = auth_service.create_auth_session(session, user.id)
    client.cookies.set(AUTH_SESSION_COOKIE_NAME, raw_token)
    return auth_session, raw_token


@pytest.mark.parametrize(
    ("has_password", "has_google"),
    [(True, False), (False, True), (True, True)],
)
def test_account_metadata_reports_only_server_derived_authentication_methods(
    client: TestClient,
    db_session: Session,
    has_password: bool,
    has_google: bool,
) -> None:
    user = create_user(db_session)
    if has_password:
        add_password(db_session, user, "existing secure password")
    if has_google:
        auth_service.link_identity(
            db_session,
            user_id=user.id,
            provider="google",
            provider_subject="private-google-subject",
        )
    authenticate(client, db_session, user)

    response = client.get("/auth/account")

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"] == {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "email_verified_at": payload["user"]["email_verified_at"],
    }
    assert payload["user"]["email_verified_at"] is not None
    assert payload["authentication_methods"] == {
        "password": has_password,
        "google": has_google,
    }
    serialized = response.text
    assert "private-google-subject" not in serialized
    assert "password_hash" not in serialized
    assert "token" not in serialized


def test_account_metadata_requires_authentication(client: TestClient) -> None:
    response = client.get("/auth/account")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_profile_update_preserves_membership_and_platform_admin(
    client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session)
    organization = organization_service.create_organization(
        db_session, "Account Organization", user.id
    )
    platform_admin = PlatformAdmin(user_id=user.id)
    db_session.add(platform_admin)
    db_session.commit()
    membership = db_session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.organization_id == organization.id,
        )
    )
    assert membership is not None
    authenticate(client, db_session, user)

    response = client.patch(
        f"/users/{user.id}", json={"name": "  Updated Account Name  "}
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Updated Account Name"
    assert db_session.get(OrganizationMembership, membership.id).role == "owner"
    assert db_session.get(PlatformAdmin, platform_admin.id) is not None


def test_change_password_preserves_current_session_and_account_access(
    client: TestClient, db_session: Session
) -> None:
    old_password = "existing secure password"
    new_password = "new secure password value"
    user = create_user(db_session)
    credential = add_password(db_session, user, old_password)
    identity = auth_service.link_identity(
        db_session,
        user_id=user.id,
        provider="google",
        provider_subject="password-change-google-subject",
    )
    organization = organization_service.create_organization(
        db_session, "Password Organization", user.id
    )
    platform_admin = PlatformAdmin(user_id=user.id)
    db_session.add(platform_admin)
    db_session.commit()
    membership = db_session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.organization_id == organization.id,
        )
    )
    assert membership is not None
    current_session, current_token = authenticate(client, db_session, user)
    second_session, second_token = auth_service.create_auth_session(db_session, user.id)
    third_session, third_token = auth_service.create_auth_session(db_session, user.id)

    response = client.post(
        "/auth/password/change",
        json={"current_password": old_password, "new_password": new_password},
    )

    assert response.status_code == 200
    assert response.json() == {"message": "Password updated successfully."}
    db_session.refresh(credential)
    db_session.refresh(current_session)
    db_session.refresh(second_session)
    db_session.refresh(third_session)
    assert credential.password_hash.startswith("$argon2id$")
    assert not local._verify_password(credential.password_hash, old_password)
    assert local._verify_password(credential.password_hash, new_password)
    assert current_session.revoked_at is None
    assert second_session.revoked_at is not None
    assert third_session.revoked_at is not None

    client.cookies.set(AUTH_SESSION_COOKIE_NAME, current_token)
    assert client.get("/auth/me").status_code == 200
    client.cookies.set(AUTH_SESSION_COOKIE_NAME, second_token)
    assert client.get("/auth/me").status_code == 401
    client.cookies.set(AUTH_SESSION_COOKIE_NAME, third_token)
    assert client.get("/auth/me").status_code == 401
    assert client.post(
        "/auth/login",
        json={"email": user.email, "password": old_password},
    ).status_code == 401
    assert client.post(
        "/auth/login",
        json={"email": user.email, "password": new_password},
    ).status_code == 200

    assert db_session.get(AuthIdentity, identity.id) is not None
    assert db_session.get(OrganizationMembership, membership.id).role == "owner"
    assert db_session.get(PlatformAdmin, platform_admin.id) is not None


def test_change_password_rejections_do_not_modify_password_or_sessions(
    client: TestClient, db_session: Session
) -> None:
    password = "existing secure password"
    user = create_user(db_session)
    credential = add_password(db_session, user, password)
    _, _ = authenticate(client, db_session, user)
    other_session, _ = auth_service.create_auth_session(db_session, user.id)
    original_hash = credential.password_hash

    wrong = client.post(
        "/auth/password/change",
        json={
            "current_password": "incorrect password value",
            "new_password": "another secure password",
        },
    )
    same = client.post(
        "/auth/password/change",
        json={"current_password": password, "new_password": password},
    )
    short = client.post(
        "/auth/password/change",
        json={"current_password": password, "new_password": "short"},
    )
    overlong = client.post(
        "/auth/password/change",
        json={"current_password": password, "new_password": "x" * 257},
    )

    db_session.refresh(credential)
    db_session.refresh(other_session)
    assert wrong.status_code == 400
    assert wrong.json() == {"detail": "Current password is incorrect."}
    assert same.status_code == 400
    assert same.json() == {
        "detail": "New password must be different from the current password."
    }
    assert short.status_code == overlong.status_code == 422
    assert credential.password_hash == original_hash
    assert other_session.revoked_at is None


def test_change_password_rejects_user_without_local_credential(
    client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session)
    auth_service.link_identity(
        db_session,
        user_id=user.id,
        provider="google",
        provider_subject="google-only-change-subject",
    )
    authenticate(client, db_session, user)

    response = client.post(
        "/auth/password/change",
        json={
            "current_password": "irrelevant current password",
            "new_password": "new secure password value",
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Password authentication is not configured."
    }


def test_password_change_is_atomic_when_session_revocation_fails(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    password = "existing secure password"
    user = create_user(db_session)
    credential = add_password(db_session, user, password)
    current_session, _ = auth_service.create_auth_session(db_session, user.id)
    other_session, _ = auth_service.create_auth_session(db_session, user.id)
    original_hash = credential.password_hash

    def fail_revocation(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("forced revocation failure")

    monkeypatch.setattr(
        auth_repository, "revoke_other_active_auth_sessions", fail_revocation
    )

    with pytest.raises(RuntimeError, match="forced revocation failure"):
        local.change_password(
            db_session,
            user_id=user.id,
            current_auth_session_id=current_session.id,
            current_password=password,
            new_password="new secure password value",
        )

    db_session.refresh(credential)
    db_session.refresh(other_session)
    assert credential.password_hash == original_hash
    assert other_session.revoked_at is None


def test_concurrent_password_changes_allow_exactly_one_stale_password_use(
    test_engine: Engine,
) -> None:
    email = f"password-concurrency-{uuid4().hex}@example.com"
    old_password = "concurrent original password"
    with Session(test_engine) as setup_session:
        user = create_user(setup_session, email=email)
        add_password(setup_session, user, old_password)
        first_session, _ = auth_service.create_auth_session(setup_session, user.id)
        second_session, _ = auth_service.create_auth_session(setup_session, user.id)
        user_id = user.id
        session_ids = [first_session.id, second_session.id]
    start = Barrier(2)

    def change_once(index: int) -> str:
        with Session(test_engine) as session:
            start.wait(timeout=10)
            try:
                local.change_password(
                    session,
                    user_id=user_id,
                    current_auth_session_id=session_ids[index],
                    current_password=old_password,
                    new_password=f"concurrent new password {index}",
                )
            except local.IncorrectCurrentPasswordError:
                return "rejected"
            return "changed"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [
                future.result(timeout=30)
                for future in [executor.submit(change_once, 0), executor.submit(change_once, 1)]
            ]
        with Session(test_engine) as session:
            credential = session.scalar(
                select(LocalCredential).where(LocalCredential.user_id == user_id)
            )
            assert credential is not None
            final_hash = credential.password_hash
        assert sorted(results) == ["changed", "rejected"]
        assert not local._verify_password(final_hash, old_password)
        assert any(
            local._verify_password(final_hash, f"concurrent new password {index}")
            for index in range(2)
        )
    finally:
        with Session(test_engine) as cleanup_session:
            cleanup_session.execute(
                delete(AuthSession).where(AuthSession.user_id == user_id)
            )
            cleanup_session.execute(
                delete(LocalCredential).where(LocalCredential.user_id == user_id)
            )
            cleanup_session.execute(delete(User).where(User.id == user_id))
            cleanup_session.commit()


def test_google_only_user_enrolls_password_for_same_account_after_email_proof(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = create_user(db_session, email="google-enrollment@example.com")
    identity = auth_service.link_identity(
        db_session,
        user_id=user.id,
        provider="google",
        provider_subject="google-enrollment-subject",
    )
    organization = organization_service.create_organization(
        db_session, "Enrollment Organization", user.id
    )
    platform_admin = PlatformAdmin(user_id=user.id)
    db_session.add(platform_admin)
    db_session.commit()
    membership = db_session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.organization_id == organization.id,
        )
    )
    assert membership is not None
    _, current_token = authenticate(client, db_session, user)
    delivered: list[tuple[str, str, bool]] = []
    monkeypatch.setattr(smtp, "ensure_email_delivery_configured", lambda: None)

    def capture_delivery(*, recipient: str, raw_token: str) -> None:
        delivered.append((recipient, raw_token, db_session.in_transaction()))

    monkeypatch.setattr(smtp, "send_verification_email", capture_delivery)

    start_response = client.post(
        "/auth/password/enrollment/start",
        json={"email": "another-user@example.com", "user_id": str(uuid4())},
    )

    assert start_response.status_code == 202
    assert delivered[0][0] == user.email
    assert delivered[0][2] is False
    raw_token = delivered[0][1]
    assert raw_token not in start_response.text
    verification = db_session.scalar(
        select(EmailVerification).where(EmailVerification.user_id == user.id)
    )
    assert verification is not None
    assert verification.token_hash == hashlib.sha256(raw_token.encode()).hexdigest()
    assert verification.token_hash != raw_token
    assert db_session.scalar(
        select(LocalCredential).where(LocalCredential.user_id == user.id)
    ) is None

    completion = client.post(
        "/auth/email-verifications/complete",
        json={"token": raw_token, "password": "enrolled secure password"},
    )

    assert completion.status_code == 200
    assert completion.json()["id"] == str(user.id)
    assert client.cookies.get(AUTH_SESSION_COOKIE_NAME) == current_token
    assert db_session.scalar(
        select(func.count()).select_from(User).where(User.email == user.email)
    ) == 1
    assert db_session.scalar(
        select(func.count()).select_from(AuthSession).where(AuthSession.user_id == user.id)
    ) == 1
    credential = db_session.scalar(
        select(LocalCredential).where(LocalCredential.user_id == user.id)
    )
    assert credential is not None
    assert credential.password_hash.startswith("$argon2id$")
    assert db_session.get(AuthIdentity, identity.id) is not None
    assert db_session.get(OrganizationMembership, membership.id).role == "owner"
    assert db_session.get(PlatformAdmin, platform_admin.id) is not None

    assert client.post("/auth/password/enrollment/start").status_code == 409
    assert client.post(
        "/auth/email-verifications/complete",
        json={"token": raw_token, "password": "another secure password"},
    ).status_code == 409


def test_password_enrollment_requires_authentication_and_verified_email(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smtp, "ensure_email_delivery_configured", lambda: None)
    unauthenticated = client.post("/auth/password/enrollment/start")
    user = create_user(db_session, verified=False)
    authenticate(client, db_session, user)
    unverified = client.post("/auth/password/enrollment/start")

    assert unauthenticated.status_code == 401
    assert unverified.status_code == 403
    assert db_session.scalar(select(func.count()).select_from(EmailVerification)) == 0


def test_authenticated_user_cannot_complete_another_users_password_enrollment(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_user = create_user(
        db_session, email="password-enrollment-target@example.com"
    )
    auth_service.link_identity(
        db_session,
        user_id=target_user.id,
        provider="google",
        provider_subject="password-enrollment-target-subject",
    )
    authenticate(client, db_session, target_user)
    delivered_tokens: list[str] = []
    monkeypatch.setattr(smtp, "ensure_email_delivery_configured", lambda: None)
    monkeypatch.setattr(
        smtp,
        "send_verification_email",
        lambda *, recipient, raw_token: delivered_tokens.append(raw_token),
    )
    assert client.post("/auth/password/enrollment/start").status_code == 202

    other_user = create_user(
        db_session,
        email="password-enrollment-other@example.com",
    )
    authenticate(client, db_session, other_user)
    completion = client.post(
        "/auth/email-verifications/complete",
        json={
            "token": delivered_tokens[0],
            "password": "target secure password",
        },
    )

    assert completion.status_code == 400
    assert completion.json() == {"detail": "Verification link is invalid."}
    assert db_session.scalar(
        select(LocalCredential).where(LocalCredential.user_id == target_user.id)
    ) is None
    verification = db_session.scalar(
        select(EmailVerification).where(
            EmailVerification.user_id == target_user.id
        )
    )
    assert verification is not None
    assert verification.used_at is None
