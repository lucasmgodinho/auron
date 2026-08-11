from uuid import UUID

from sqlalchemy.orm import Session

from app.core.organizations import repository
from app.core.organizations.model import Organization


class OrganizationNotFoundError(Exception):
    pass


def _normalize_name(name: str) -> str:
    normalized_name = name.strip()
    if not normalized_name or len(normalized_name) > 255:
        raise ValueError("Organization name must contain between 1 and 255 characters")
    return normalized_name


def create_organization(session: Session, name: str) -> Organization:
    return repository.create_organization(session, _normalize_name(name))


def get_organization(session: Session, organization_id: UUID) -> Organization:
    organization = repository.get_organization(session, organization_id)
    if organization is None:
        raise OrganizationNotFoundError
    return organization


def list_organizations(session: Session, limit: int, offset: int) -> list[Organization]:
    return repository.list_organizations(session, limit, offset)


def update_organization_name(
    session: Session, organization_id: UUID, name: str
) -> Organization:
    organization = get_organization(session, organization_id)
    return repository.update_organization_name(session, organization, _normalize_name(name))
