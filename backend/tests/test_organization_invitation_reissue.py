import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.organization_invitations import service as invitation_service
from app.core.organization_invitations.model import OrganizationInvitation
from app.core.organization_memberships import repository as membership_repository
from app.core.organization_memberships.model import OrganizationMembership
from app.core.organizations import service as organization_service
from app.core.organizations.model import Organization
from app.core.platform_admin import service as platform_admin_service
from app.core.platform_admin.schemas import PlatformOrganizationCreate
from app.core.users import service as user_service


def provision_invitation(
    session: Session,
    *,
    email: str = "invited@example.com",
    name: str = "Reissue Organization",
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


def test_expired_invitation_is_reissued_in_place(db_session: Session) -> None:
    organization, invitation = provision_invitation(db_session)
    invitation.expires_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()
    invitation_id = invitation.id
    created_at = invitation.created_at
    previous_expiration = invitation.expires_at

    reissued = invitation_service.reissue_expired_invitation(
        db_session,
        organization_id=organization.id,
        email="  INVITED@EXAMPLE.COM  ",
        expires_hours=24,
    )

    invitation_count = db_session.scalar(
        select(func.count())
        .select_from(OrganizationInvitation)
        .where(OrganizationInvitation.organization_id == organization.id)
    )
    membership_count = db_session.scalar(
        select(func.count())
        .select_from(OrganizationMembership)
        .where(OrganizationMembership.organization_id == organization.id)
    )
    assert reissued.id == invitation_id
    assert reissued.organization_id == organization.id
    assert reissued.email == "invited@example.com"
    assert reissued.created_at == created_at
    assert reissued.accepted_at is None
    assert reissued.expires_at > datetime.now(UTC)
    assert reissued.expires_at > previous_expiration
    assert invitation_count == 1
    assert membership_count == 0


def test_reissue_does_not_modify_existing_membership_role(
    db_session: Session,
) -> None:
    owner = user_service.create_user(
        db_session, email="owner@example.com", name="Owner"
    )
    organization = organization_service.create_organization(
        db_session, "Existing Membership", owner.id
    )
    invitation = OrganizationInvitation(
        organization_id=organization.id,
        email=owner.email,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.add(invitation)
    db_session.commit()

    invitation_service.reissue_expired_invitation(
        db_session,
        organization_id=organization.id,
        email=owner.email,
    )

    membership = membership_repository.get_membership_for_user_organization(
        db_session,
        user_id=owner.id,
        organization_id=organization.id,
    )
    assert membership is not None
    assert membership.role == "owner"


def test_active_invitation_cannot_be_reissued(db_session: Session) -> None:
    organization, invitation = provision_invitation(db_session)
    expires_at = invitation.expires_at

    with pytest.raises(invitation_service.OrganizationInvitationActiveError):
        invitation_service.reissue_expired_invitation(
            db_session,
            organization_id=organization.id,
            email=invitation.email,
        )

    db_session.refresh(invitation)
    assert invitation.expires_at == expires_at
    assert invitation.accepted_at is None


def test_accepted_invitation_cannot_be_reissued(db_session: Session) -> None:
    organization, invitation = provision_invitation(db_session)
    accepted_at = datetime.now(UTC)
    invitation.accepted_at = accepted_at
    invitation.expires_at = accepted_at - timedelta(hours=1)
    db_session.commit()

    with pytest.raises(invitation_service.OrganizationInvitationAcceptedError):
        invitation_service.reissue_expired_invitation(
            db_session,
            organization_id=organization.id,
            email=invitation.email,
        )

    db_session.refresh(invitation)
    assert invitation.accepted_at == accepted_at


def test_reissue_requires_existing_organization_and_invitation(
    db_session: Session,
) -> None:
    organization, _ = provision_invitation(db_session)

    with pytest.raises(
        invitation_service.OrganizationInvitationOrganizationNotFoundError
    ):
        invitation_service.reissue_expired_invitation(
            db_session,
            organization_id=uuid4(),
            email="missing@example.com",
        )
    with pytest.raises(invitation_service.OrganizationInvitationNotFoundError):
        invitation_service.reissue_expired_invitation(
            db_session,
            organization_id=organization.id,
            email="missing@example.com",
        )


@pytest.mark.parametrize(
    ("email", "expires_hours"),
    [
        ("not-an-email", 168),
        ("valid@example.com", 0),
        ("valid@example.com", -1),
    ],
)
def test_reissue_validates_email_and_expiration(
    db_session: Session, email: str, expires_hours: int
) -> None:
    organization, invitation = provision_invitation(db_session)
    invitation.expires_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()
    previous_expiration = invitation.expires_at

    with pytest.raises(ValidationError):
        invitation_service.reissue_expired_invitation(
            db_session,
            organization_id=organization.id,
            email=email,
            expires_hours=expires_hours,
        )

    db_session.refresh(invitation)
    assert invitation.expires_at == previous_expiration


def test_reissue_cli_is_isolated_and_enforces_lifecycle(test_engine: Engine) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    database_url = test_engine.url.render_as_string(hide_password=False)
    environment["DATABASE_URL"] = database_url
    suffix = uuid4().hex
    organization_id: UUID | None = None
    expired_invitation_id: UUID | None = None
    expired_created_at = None

    help_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.scripts.reissue_organization_invitation",
            "--help",
        ],
        cwd=backend_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert help_result.returncode == 0
    assert "--organization-id" in help_result.stdout
    assert "--expires-hours" in help_result.stdout

    try:
        with Session(test_engine) as setup_session:
            emails = {
                "expired": f"expired-{suffix}@example.com",
                "active": f"active-{suffix}@example.com",
                "accepted": f"accepted-{suffix}@example.com",
            }
            organization = platform_admin_service.provision_organization(
                setup_session,
                PlatformOrganizationCreate(
                    name=f"CLI reissue {suffix}",
                    invitation_emails=list(emails.values()),
                ),
            )
            organization_id = organization.id
            invitations = {
                invitation.email: invitation
                for invitation in setup_session.scalars(
                    select(OrganizationInvitation).where(
                        OrganizationInvitation.organization_id == organization.id
                    )
                )
            }
            expired = invitations[emails["expired"]]
            expired.expires_at = datetime.now(UTC) - timedelta(hours=1)
            accepted = invitations[emails["accepted"]]
            accepted.accepted_at = datetime.now(UTC)
            setup_session.commit()
            expired_invitation_id = expired.id
            expired_created_at = expired.created_at

        def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app.scripts.reissue_organization_invitation",
                    *arguments,
                ],
                cwd=backend_root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

        invalid_email = run_cli(
            "--organization-id", str(organization_id), "--email", "invalid"
        )
        invalid_hours = run_cli(
            "--organization-id",
            str(organization_id),
            "--email",
            emails["expired"],
            "--expires-hours",
            "0",
        )
        missing_organization = run_cli(
            "--organization-id",
            str(uuid4()),
            "--email",
            emails["expired"],
        )
        missing_invitation = run_cli(
            "--organization-id",
            str(organization_id),
            "--email",
            f"missing-{suffix}@example.com",
        )
        active = run_cli(
            "--organization-id",
            str(organization_id),
            "--email",
            emails["active"],
        )
        accepted = run_cli(
            "--organization-id",
            str(organization_id),
            "--email",
            emails["accepted"],
        )
        success = run_cli(
            "--organization-id",
            str(organization_id),
            "--email",
            emails["expired"].upper(),
            "--expires-hours",
            "24",
        )
        repeated = run_cli(
            "--organization-id",
            str(organization_id),
            "--email",
            emails["expired"],
        )

        assert invalid_email.returncode != 0
        assert invalid_hours.returncode != 0
        assert missing_organization.returncode != 0
        assert "Organization does not exist" in missing_organization.stderr
        assert missing_invitation.returncode != 0
        assert "invitation does not exist" in missing_invitation.stderr
        assert active.returncode != 0
        assert "still active" in active.stderr
        assert accepted.returncode != 0
        assert "cannot be reissued" in accepted.stderr
        assert success.returncode == 0, success.stderr
        assert "Invitation reissued." in success.stdout
        assert emails["expired"] in success.stdout
        assert database_url not in success.stdout
        assert repeated.returncode != 0
        assert "still active" in repeated.stderr

        with Session(test_engine) as verification_session:
            invitation = verification_session.get(
                OrganizationInvitation, expired_invitation_id
            )
            invitation_count = verification_session.scalar(
                select(func.count())
                .select_from(OrganizationInvitation)
                .where(OrganizationInvitation.organization_id == organization_id)
            )
            membership_count = verification_session.scalar(
                select(func.count())
                .select_from(OrganizationMembership)
                .where(OrganizationMembership.organization_id == organization_id)
            )
        assert invitation is not None
        assert invitation.id == expired_invitation_id
        assert invitation.created_at == expired_created_at
        assert invitation.accepted_at is None
        assert invitation.expires_at > datetime.now(UTC)
        assert invitation_count == 3
        assert membership_count == 0
    finally:
        if organization_id is not None:
            with Session(test_engine) as cleanup_session:
                cleanup_session.execute(
                    delete(OrganizationInvitation).where(
                        OrganizationInvitation.organization_id == organization_id
                    )
                )
                cleanup_session.execute(
                    delete(Organization).where(Organization.id == organization_id)
                )
                cleanup_session.commit()
