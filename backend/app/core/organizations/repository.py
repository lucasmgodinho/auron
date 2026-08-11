from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.organizations.model import Organization


def create_organization(session: Session, name: str) -> Organization:
    organization = Organization(name=name)
    session.add(organization)
    session.commit()
    session.refresh(organization)
    return organization


def get_organization(session: Session, organization_id: UUID) -> Organization | None:
    return session.get(Organization, organization_id)


def list_organizations(session: Session, limit: int, offset: int) -> list[Organization]:
    statement = (
        select(Organization)
        .order_by(Organization.created_at, Organization.id)
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(statement))


def update_organization_name(
    session: Session, organization: Organization, name: str
) -> Organization:
    organization.name = name
    session.commit()
    session.refresh(organization)
    return organization
