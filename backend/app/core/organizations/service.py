from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.organization_memberships import repository as membership_repository
from app.core.organization_memberships.model import OrganizationMembership
from app.core.organizations import repository
from app.core.organizations.model import Organization


class OrganizationNotFoundError(Exception):
    pass


class OrganizationAccessDeniedError(Exception):
    pass


def _normalize_name(name: str) -> str:
    normalized_name = name.strip()
    if not normalized_name or len(normalized_name) > 255:
        raise ValueError("Organization name must contain between 1 and 255 characters")
    return normalized_name


def create_organization(
    session: Session, name: str, owner_user_id: UUID
) -> Organization:
    try:
        return repository.create_organization(
            session, _normalize_name(name), owner_user_id
        )
    except IntegrityError:
        session.rollback()
        raise


def get_organization(session: Session, organization_id: UUID) -> Organization:
    organization = repository.get_organization(session, organization_id)
    if organization is None:
        raise OrganizationNotFoundError
    return organization


def get_organization_for_update(
    session: Session, organization_id: UUID
) -> Organization:
    organization = repository.get_organization_for_update(session, organization_id)
    if organization is None:
        raise OrganizationNotFoundError
    return organization


def _require_membership(
    session: Session, organization_id: UUID, user_id: UUID
) -> OrganizationMembership:
    membership = membership_repository.get_membership_for_user_organization(
        session, user_id=user_id, organization_id=organization_id
    )
    if membership is None:
        raise OrganizationAccessDeniedError
    return membership


def get_organization_for_user(
    session: Session, organization_id: UUID, current_user_id: UUID
) -> Organization:
    organization = get_organization(session, organization_id)
    _require_membership(session, organization_id, current_user_id)
    return organization


def list_organizations_for_user(
    session: Session, current_user_id: UUID, limit: int, offset: int
) -> list[Organization]:
    return repository.list_organizations_for_user(
        session, current_user_id, limit, offset
    )


def update_organization_name(
    session: Session, organization_id: UUID, current_user_id: UUID, name: str
) -> Organization:
    organization = get_organization_for_update(session, organization_id)
    membership = _require_membership(session, organization_id, current_user_id)
    if membership.role not in {"owner", "admin"}:
        raise OrganizationAccessDeniedError
    return repository.update_organization_name(session, organization, _normalize_name(name))
