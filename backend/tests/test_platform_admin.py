import os
import subprocess
import sys
from pathlib import Path
from typing import Never
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.auth import service as auth_service
from app.core.auth.dependencies import AUTH_SESSION_COOKIE_NAME
from app.core.organization_invitations import repository as invitation_repository
from app.core.organization_invitations.model import OrganizationInvitation
from app.core.organization_memberships.model import OrganizationMembership
from app.core.organizations import service as organization_service
from app.core.organizations.model import Organization
from app.core.platform_admin import service as platform_admin_service
from app.core.platform_admin.model import PlatformAdmin
from app.core.platform_admin.schemas import PlatformOrganizationCreate
from app.core.users import service as user_service
from app.core.users.model import User


def create_user(
    session: Session,
    *,
    email: str = "operator@example.com",
    name: str = "Operator",
) -> User:
    return user_service.create_user(session, email=email, name=name)


def authenticate(client: TestClient, session: Session, user: User) -> None:
    _, raw_token = auth_service.create_auth_session(session, user.id)
    client.cookies.set(AUTH_SESSION_COOKIE_NAME, raw_token)


def grant_platform_admin(session: Session, user: User) -> PlatformAdmin:
    platform_admin, created = platform_admin_service.grant_platform_admin(
        session, user.email
    )
    assert created
    return platform_admin


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/platform-admin/me", None),
        ("get", "/platform-admin/organizations", None),
        (
            "post",
            "/platform-admin/organizations",
            {"name": "Acme", "invitation_emails": ["owner@example.com"]},
        ),
    ],
)
def test_platform_admin_endpoints_require_authentication(
    client: TestClient,
    method: str,
    path: str,
    payload: dict[str, object] | None,
) -> None:
    response = client.request(method, path, json=payload)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_normal_user_is_not_platform_admin(
    client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session)
    authenticate(client, db_session, user)

    status_response = client.get("/platform-admin/me")
    list_response = client.get("/platform-admin/organizations")
    create_response = client.post(
        "/platform-admin/organizations",
        json={"name": "Forbidden", "invitation_emails": ["owner@example.com"]},
    )

    assert status_response.status_code == 403
    assert list_response.status_code == 403
    assert create_response.status_code == 403
    assert db_session.scalar(select(func.count()).select_from(Organization)) == 0


def test_platform_admin_record_grants_status_and_global_listing(
    client: TestClient, db_session: Session
) -> None:
    operator = create_user(db_session)
    owner = create_user(db_session, email="owner@example.com", name="Owner")
    organization = organization_service.create_organization(
        db_session, "Existing customer", owner.id
    )
    grant_platform_admin(db_session, operator)
    authenticate(client, db_session, operator)

    status_response = client.get("/platform-admin/me")
    list_response = client.get("/platform-admin/organizations")
    tenant_response = client.get(f"/organizations/{organization.id}")

    assert status_response.status_code == 200
    assert status_response.json() == {"is_platform_admin": True}
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [str(organization.id)]
    assert tenant_response.status_code == 403


def test_platform_admin_provisions_organization_and_normalized_invitations(
    client: TestClient, db_session: Session
) -> None:
    operator = create_user(db_session)
    grant_platform_admin(db_session, operator)
    authenticate(client, db_session, operator)

    response = client.post(
        "/platform-admin/organizations",
        json={
            "name": "  Engedrain  ",
            "invitation_emails": [
                "  PERSON@EXAMPLE.COM  ",
                "person@example.com",
                "second@example.com",
            ],
        },
    )

    assert response.status_code == 201
    organization_id = response.json()["id"]
    invitations = list(
        db_session.scalars(
            select(OrganizationInvitation)
            .where(OrganizationInvitation.organization_id == organization_id)
            .order_by(OrganizationInvitation.email)
        )
    )
    membership_count = db_session.scalar(
        select(func.count())
        .select_from(OrganizationMembership)
        .where(OrganizationMembership.organization_id == organization_id)
    )
    assert response.json()["name"] == "Engedrain"
    assert [invitation.email for invitation in invitations] == [
        "person@example.com",
        "second@example.com",
    ]
    assert all(invitation.accepted_at is None for invitation in invitations)
    assert all(invitation.expires_at > invitation.created_at for invitation in invitations)
    assert membership_count == 0
    assert not hasattr(invitations[0], "role")


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "Acme", "invitation_emails": []},
        {"name": "Acme", "invitation_emails": ["not-an-email"]},
        {"name": "   ", "invitation_emails": ["owner@example.com"]},
    ],
)
def test_platform_provisioning_validates_required_input(
    client: TestClient, db_session: Session, payload: dict[str, object]
) -> None:
    operator = create_user(db_session)
    grant_platform_admin(db_session, operator)
    authenticate(client, db_session, operator)

    response = client.post("/platform-admin/organizations", json=payload)

    assert response.status_code == 422
    assert db_session.scalar(select(func.count()).select_from(Organization)) == 0


def test_platform_provisioning_failure_is_atomic(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_add = invitation_repository.add_invitations

    def add_then_fail(*args: object, **kwargs: object) -> Never:
        original_add(*args, **kwargs)
        raise RuntimeError("simulated invitation insertion failure")

    monkeypatch.setattr(invitation_repository, "add_invitations", add_then_fail)
    payload = PlatformOrganizationCreate(
        name="Must roll back",
        invitation_emails=["first@example.com", "second@example.com"],
    )

    with pytest.raises(RuntimeError, match="simulated invitation insertion failure"):
        platform_admin_service.provision_organization(db_session, payload)

    assert db_session.scalar(select(func.count()).select_from(Organization)) == 0
    assert db_session.scalar(
        select(func.count()).select_from(OrganizationInvitation)
    ) == 0


def test_grant_platform_admin_service_is_idempotent_and_creates_no_membership(
    db_session: Session,
) -> None:
    user = create_user(db_session, email="  operator@example.com  ")

    first_admin, first_created = platform_admin_service.grant_platform_admin(
        db_session, " OPERATOR@EXAMPLE.COM "
    )
    second_admin, second_created = platform_admin_service.grant_platform_admin(
        db_session, "operator@example.com"
    )

    assert first_created is True
    assert second_created is False
    assert second_admin.id == first_admin.id
    assert first_admin.user_id == user.id
    assert db_session.scalar(
        select(func.count()).select_from(OrganizationMembership)
    ) == 0


def test_grant_platform_admin_requires_existing_user(db_session: Session) -> None:
    with pytest.raises(platform_admin_service.PlatformAdminUserNotFoundError):
        platform_admin_service.grant_platform_admin(
            db_session, "missing@example.com"
        )

    assert db_session.scalar(select(func.count()).select_from(PlatformAdmin)) == 0


def test_grant_platform_admin_cli_uses_explicit_test_database(
    test_engine: Engine,
) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["DATABASE_URL"] = test_engine.url.render_as_string(hide_password=False)
    suffix = uuid4().hex
    email = f"cli-operator-{suffix}@example.com"
    missing_email = f"missing-{suffix}@example.com"
    user_id = None

    help_result = subprocess.run(
        [sys.executable, "-m", "app.scripts.grant_platform_admin", "--help"],
        cwd=backend_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert help_result.returncode == 0
    assert "--email" in help_result.stdout

    try:
        missing_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "app.scripts.grant_platform_admin",
                "--email",
                missing_email,
            ],
            cwd=backend_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert missing_result.returncode != 0

        with Session(test_engine) as setup_session:
            user = create_user(setup_session, email=email, name="CLI Operator")
            user_id = user.id

        command = [
            sys.executable,
            "-m",
            "app.scripts.grant_platform_admin",
            "--email",
            email,
        ]
        first_result = subprocess.run(
            command,
            cwd=backend_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        second_result = subprocess.run(
            command,
            cwd=backend_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        assert first_result.returncode == 0, first_result.stderr
        assert second_result.returncode == 0, second_result.stderr
        assert "granted" in first_result.stdout
        assert "already granted" in second_result.stdout
        with Session(test_engine) as verification_session:
            admin_count = verification_session.scalar(
                select(func.count())
                .select_from(PlatformAdmin)
                .where(PlatformAdmin.user_id == user_id)
            )
            membership_count = verification_session.scalar(
                select(func.count())
                .select_from(OrganizationMembership)
                .where(OrganizationMembership.user_id == user_id)
            )
        assert admin_count == 1
        assert membership_count == 0
    finally:
        if user_id is not None:
            with Session(test_engine) as cleanup_session:
                cleanup_session.execute(
                    delete(PlatformAdmin).where(PlatformAdmin.user_id == user_id)
                )
                cleanup_session.execute(delete(User).where(User.id == user_id))
                cleanup_session.commit()
