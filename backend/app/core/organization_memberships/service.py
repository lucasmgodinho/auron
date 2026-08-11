from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.organization_memberships import repository
from app.core.organization_memberships.model import OrganizationMembership
from app.core.organizations import service as organization_service
from app.core.users import service as user_service


class MembershipNotFoundError(Exception):
    pass


class MembershipConflictError(Exception):
    pass


def create_membership(
    session: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
    role: str,
) -> OrganizationMembership:
    organization_service.get_organization(session, organization_id)
    user_service.get_user(session, user_id)

    try:
        return repository.create_membership(
            session,
            user_id=user_id,
            organization_id=organization_id,
            role=role,
        )
    except IntegrityError as error:
        session.rollback()
        raise MembershipConflictError from error


def list_organization_memberships(
    session: Session, organization_id: UUID
) -> list[OrganizationMembership]:
    organization_service.get_organization(session, organization_id)
    return repository.list_organization_memberships(session, organization_id)


def list_user_memberships(
    session: Session, user_id: UUID
) -> list[OrganizationMembership]:
    user_service.get_user(session, user_id)
    return repository.list_user_memberships(session, user_id)


def update_membership_role(
    session: Session,
    *,
    organization_id: UUID,
    membership_id: UUID,
    role: str,
) -> OrganizationMembership:
    organization_service.get_organization(session, organization_id)
    membership = repository.get_membership(
        session,
        membership_id=membership_id,
        organization_id=organization_id,
    )
    if membership is None:
        raise MembershipNotFoundError
    return repository.update_membership_role(session, membership, role)
