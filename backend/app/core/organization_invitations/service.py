from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.organization_invitations import repository
from app.core.organization_invitations.model import OrganizationInvitation
from app.core.organization_invitations.schemas import (
    DEFAULT_INVITATION_TTL_HOURS,
    OrganizationInvitationReissue,
    OrganizationInvitationResponse,
)
from app.core.organization_memberships import repository as membership_repository
from app.core.organizations import repository as organization_repository
from app.core.organizations.model import Organization
from app.core.users.model import User


class OrganizationInvitationNotFoundError(Exception):
    pass


class OrganizationInvitationExpiredError(Exception):
    pass


class OrganizationInvitationAcceptedError(Exception):
    pass


class OrganizationInvitationEmailMismatchError(Exception):
    pass


class OrganizationInvitationEmailUnverifiedError(Exception):
    pass


class OrganizationInvitationOrganizationNotFoundError(Exception):
    pass


class OrganizationInvitationActiveError(Exception):
    pass


def list_pending_invitations(
    session: Session, current_user: User
) -> list[OrganizationInvitationResponse]:
    rows = repository.list_pending_for_email(
        session,
        email=current_user.email,
        now=datetime.now(UTC),
    )
    return [
        OrganizationInvitationResponse(
            id=invitation.id,
            organization_id=invitation.organization_id,
            organization_name=organization_name,
            expires_at=invitation.expires_at,
        )
        for invitation, organization_name in rows
    ]


def accept_invitation(
    session: Session, *, invitation_id: UUID, current_user: User
) -> Organization:
    try:
        if current_user.email_verified_at is None:
            raise OrganizationInvitationEmailUnverifiedError
        invitation = repository.get_invitation_for_update(session, invitation_id)
        if invitation is None:
            raise OrganizationInvitationNotFoundError
        if invitation.accepted_at is not None:
            raise OrganizationInvitationAcceptedError
        if invitation.expires_at <= datetime.now(UTC):
            raise OrganizationInvitationExpiredError
        if invitation.email != current_user.email:
            raise OrganizationInvitationEmailMismatchError

        organization = organization_repository.get_organization_for_update(
            session, invitation.organization_id
        )
        if organization is None:
            raise OrganizationInvitationNotFoundError

        membership = membership_repository.get_membership_for_user_organization(
            session,
            user_id=current_user.id,
            organization_id=organization.id,
        )
        if membership is None:
            membership_count = membership_repository.count_organization_memberships(
                session, organization.id
            )
            membership_repository.add_membership(
                session,
                user_id=current_user.id,
                organization_id=organization.id,
                role="owner" if membership_count == 0 else "member",
            )
        invitation.accepted_at = datetime.now(UTC)
        session.commit()
        session.refresh(organization)
        return organization
    except Exception:
        session.rollback()
        raise


def reissue_expired_invitation(
    session: Session,
    *,
    organization_id: UUID,
    email: str,
    expires_hours: int = DEFAULT_INVITATION_TTL_HOURS,
) -> OrganizationInvitation:
    reissue = OrganizationInvitationReissue(
        email=email,
        expires_hours=expires_hours,
    )
    try:
        organization = organization_repository.get_organization(
            session, organization_id
        )
        if organization is None:
            raise OrganizationInvitationOrganizationNotFoundError

        invitation = repository.get_invitation_by_organization_email_for_update(
            session,
            organization_id=organization.id,
            email=str(reissue.email),
        )
        if invitation is None:
            raise OrganizationInvitationNotFoundError
        if invitation.accepted_at is not None:
            raise OrganizationInvitationAcceptedError
        now = datetime.now(UTC)
        if invitation.expires_at > now:
            raise OrganizationInvitationActiveError

        invitation.expires_at = now + timedelta(hours=reissue.expires_hours)
        session.commit()
        session.refresh(invitation)
        return invitation
    except Exception:
        session.rollback()
        raise
