from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.organization_invitations import repository
from app.core.organization_invitations.schemas import OrganizationInvitationResponse
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
        invitation = repository.get_invitation_for_update(session, invitation_id)
        if invitation is None:
            raise OrganizationInvitationNotFoundError
        if invitation.accepted_at is not None:
            raise OrganizationInvitationAcceptedError
        if invitation.expires_at <= datetime.now(UTC):
            raise OrganizationInvitationExpiredError
        if invitation.email != current_user.email:
            raise OrganizationInvitationEmailMismatchError

        organization = organization_repository.get_organization(
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
            membership_repository.add_membership(
                session,
                user_id=current_user.id,
                organization_id=organization.id,
                role="member",
            )
        invitation.accepted_at = datetime.now(UTC)
        session.commit()
        session.refresh(organization)
        return organization
    except Exception:
        session.rollback()
        raise
