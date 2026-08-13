from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.organization_invitations.model import OrganizationInvitation
from app.core.organizations.model import Organization


def add_invitations(
    session: Session,
    *,
    organization_id: UUID,
    emails: list[str],
    expires_at: datetime,
) -> list[OrganizationInvitation]:
    invitations = [
        OrganizationInvitation(
            organization_id=organization_id,
            email=email,
            expires_at=expires_at,
        )
        for email in emails
    ]
    session.add_all(invitations)
    return invitations


def list_pending_for_email(
    session: Session, *, email: str, now: datetime
) -> list[tuple[OrganizationInvitation, str]]:
    statement = (
        select(OrganizationInvitation, Organization.name)
        .join(Organization, Organization.id == OrganizationInvitation.organization_id)
        .where(
            OrganizationInvitation.email == email,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.expires_at > now,
        )
        .order_by(OrganizationInvitation.created_at, OrganizationInvitation.id)
    )
    return [(row[0], row[1]) for row in session.execute(statement)]


def get_invitation_for_update(
    session: Session, invitation_id: UUID
) -> OrganizationInvitation | None:
    statement = (
        select(OrganizationInvitation)
        .where(OrganizationInvitation.id == invitation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return session.scalar(statement)
