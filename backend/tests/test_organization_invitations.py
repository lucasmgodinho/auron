from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import Never
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.auth import service as auth_service
from app.core.auth.dependencies import AUTH_SESSION_COOKIE_NAME
from app.core.organization_invitations import service as invitation_service
from app.core.organization_invitations.model import OrganizationInvitation
from app.core.organization_memberships import repository as membership_repository
from app.core.organization_memberships.model import OrganizationMembership
from app.core.organizations import service as organization_service
from app.core.organizations.model import Organization
from app.core.platform_admin import service as platform_admin_service
from app.core.platform_admin.schemas import PlatformOrganizationCreate
from app.core.users import service as user_service
from app.core.users.model import User


def create_user(
    session: Session,
    *,
    email: str = "invited@example.com",
    name: str = "Invited User",
) -> User:
    return user_service.create_user(session, email=email, name=name)


def authenticate(client: TestClient, session: Session, user: User) -> None:
    _, raw_token = auth_service.create_auth_session(session, user.id)
    client.cookies.set(AUTH_SESSION_COOKIE_NAME, raw_token)


def create_organization_invitation(
    session: Session,
    *,
    email: str = "invited@example.com",
    name: str = "Invited Organization",
) -> tuple[Organization, OrganizationInvitation]:
    organization = platform_admin_service.provision_organization(
        session,
        PlatformOrganizationCreate(name=name, invitation_emails=[email]),
    )
    invitation = session.scalar(
        select(OrganizationInvitation).where(
            OrganizationInvitation.organization_id == organization.id,
            OrganizationInvitation.email == email.strip().lower(),
        )
    )
    assert invitation is not None
    return organization, invitation


def test_invitation_endpoints_require_authentication(client: TestClient) -> None:
    list_response = client.get("/organization-invitations/me")
    accept_response = client.post(
        f"/organization-invitations/{uuid4()}/accept"
    )

    assert list_response.status_code == 401
    assert accept_response.status_code == 401


def test_user_sees_only_matching_pending_unexpired_invitations(
    client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session)
    matching_organization, matching = create_organization_invitation(db_session)
    _, other = create_organization_invitation(
        db_session,
        email="other@example.com",
        name="Other Organization",
    )
    _, expired = create_organization_invitation(
        db_session,
        email=user.email,
        name="Expired Organization",
    )
    expired.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    _, accepted = create_organization_invitation(
        db_session,
        email=user.email,
        name="Accepted Organization",
    )
    accepted.accepted_at = datetime.now(UTC)
    db_session.commit()
    authenticate(client, db_session, user)

    response = client.get(
        "/organization-invitations/me",
        params={"email": other.email},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(matching.id),
            "organization_id": str(matching_organization.id),
            "organization_name": matching_organization.name,
            "expires_at": matching.expires_at.isoformat().replace("+00:00", "Z"),
        }
    ]


def test_matching_user_accepts_invitation_and_gains_only_invited_organization(
    client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session)
    organization, invitation = create_organization_invitation(db_session)
    other_organization, _ = create_organization_invitation(
        db_session,
        email="other@example.com",
        name="Other Organization",
    )
    authenticate(client, db_session, user)

    response = client.post(
        f"/organization-invitations/{invitation.id}/accept"
    )

    membership = membership_repository.get_membership_for_user_organization(
        db_session,
        user_id=user.id,
        organization_id=organization.id,
    )
    db_session.refresh(invitation)
    assert response.status_code == 200
    assert response.json()["id"] == str(organization.id)
    assert membership is not None
    assert membership.role == "member"
    assert invitation.accepted_at is not None
    assert client.get(f"/organizations/{organization.id}").status_code == 200
    assert client.get(f"/organizations/{other_organization.id}").status_code == 403


def test_another_user_cannot_accept_invitation(
    client: TestClient, db_session: Session
) -> None:
    attacker = create_user(
        db_session, email="attacker@example.com", name="Attacker"
    )
    _, invitation = create_organization_invitation(db_session)
    authenticate(client, db_session, attacker)

    response = client.post(
        f"/organization-invitations/{invitation.id}/accept"
    )

    db_session.refresh(invitation)
    assert response.status_code == 403
    assert invitation.accepted_at is None
    assert db_session.scalar(
        select(func.count()).select_from(OrganizationMembership)
    ) == 0


def test_expired_invitation_cannot_be_accepted(
    client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session)
    _, invitation = create_organization_invitation(db_session)
    invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    authenticate(client, db_session, user)

    response = client.post(
        f"/organization-invitations/{invitation.id}/accept"
    )

    db_session.refresh(invitation)
    assert response.status_code == 410
    assert invitation.accepted_at is None
    assert db_session.scalar(
        select(func.count()).select_from(OrganizationMembership)
    ) == 0


def test_accepted_invitation_cannot_create_duplicate_membership(
    client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session)
    organization, invitation = create_organization_invitation(db_session)
    authenticate(client, db_session, user)

    first_response = client.post(
        f"/organization-invitations/{invitation.id}/accept"
    )
    second_response = client.post(
        f"/organization-invitations/{invitation.id}/accept"
    )

    membership_count = db_session.scalar(
        select(func.count())
        .select_from(OrganizationMembership)
        .where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.organization_id == organization.id,
        )
    )
    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert membership_count == 1


def test_existing_membership_acceptance_marks_invitation_without_duplicate(
    client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session)
    organization = organization_service.create_organization(
        db_session, "Existing Membership", user.id
    )
    invitation = OrganizationInvitation(
        organization_id=organization.id,
        email=user.email,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add(invitation)
    db_session.commit()
    authenticate(client, db_session, user)

    response = client.post(
        f"/organization-invitations/{invitation.id}/accept"
    )

    db_session.refresh(invitation)
    memberships = list(
        db_session.scalars(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == user.id,
                OrganizationMembership.organization_id == organization.id,
            )
        )
    )
    assert response.status_code == 200
    assert invitation.accepted_at is not None
    assert len(memberships) == 1
    assert memberships[0].role == "owner"


def test_acceptance_failure_rolls_back_membership_and_invitation(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = create_user(db_session)
    organization, invitation = create_organization_invitation(db_session)
    original_add = membership_repository.add_membership

    def add_then_fail(*args: object, **kwargs: object) -> Never:
        original_add(*args, **kwargs)
        raise RuntimeError("simulated membership insertion failure")

    monkeypatch.setattr(membership_repository, "add_membership", add_then_fail)

    with pytest.raises(RuntimeError, match="simulated membership insertion failure"):
        invitation_service.accept_invitation(
            db_session,
            invitation_id=invitation.id,
            current_user=user,
        )

    db_session.refresh(invitation)
    assert invitation.accepted_at is None
    assert db_session.scalar(
        select(func.count())
        .select_from(OrganizationMembership)
        .where(OrganizationMembership.organization_id == organization.id)
    ) == 0


def test_concurrent_acceptance_creates_one_membership(test_engine: Engine) -> None:
    suffix = uuid4().hex
    email = f"concurrent-{suffix}@example.com"
    organization_name = f"Concurrent invitation {suffix}"
    start = Barrier(2)
    user_id: UUID | None = None
    organization_id: UUID | None = None
    invitation_id: UUID | None = None

    try:
        with Session(test_engine) as setup_session:
            user = create_user(setup_session, email=email, name="Concurrent User")
            organization, invitation = create_organization_invitation(
                setup_session,
                email=email,
                name=organization_name,
            )
            user_id = user.id
            organization_id = organization.id
            invitation_id = invitation.id

        def accept() -> str:
            with Session(test_engine) as session:
                current_user = session.get(User, user_id)
                assert current_user is not None
                start.wait(timeout=10)
                try:
                    invitation_service.accept_invitation(
                        session,
                        invitation_id=invitation_id,
                        current_user=current_user,
                    )
                except invitation_service.OrganizationInvitationAcceptedError:
                    return "already-accepted"
                return "accepted"

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(accept) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]

        with Session(test_engine) as verification_session:
            membership_count = verification_session.scalar(
                select(func.count())
                .select_from(OrganizationMembership)
                .where(
                    OrganizationMembership.user_id == user_id,
                    OrganizationMembership.organization_id == organization_id,
                )
            )
            stored_invitation = verification_session.get(
                OrganizationInvitation, invitation_id
            )

        assert sorted(results) == ["accepted", "already-accepted"]
        assert membership_count == 1
        assert stored_invitation is not None
        assert stored_invitation.accepted_at is not None
    finally:
        with Session(test_engine) as cleanup_session:
            if organization_id is not None:
                cleanup_session.execute(
                    delete(OrganizationMembership).where(
                        OrganizationMembership.organization_id == organization_id
                    )
                )
                cleanup_session.execute(
                    delete(OrganizationInvitation).where(
                        OrganizationInvitation.organization_id == organization_id
                    )
                )
                cleanup_session.execute(
                    delete(Organization).where(Organization.id == organization_id)
                )
            if user_id is not None:
                cleanup_session.execute(delete(User).where(User.id == user_id))
            cleanup_session.commit()
