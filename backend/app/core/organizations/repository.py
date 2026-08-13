from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.organization_memberships.model import OrganizationMembership
from app.core.organizations.model import Organization


def add_organization(session: Session, name: str) -> Organization:
    organization = Organization(name=name)
    session.add(organization)
    return organization


def create_organization(session: Session, name: str, owner_user_id: UUID) -> Organization:
    organization = add_organization(session, name)
    session.flush()
    session.add(
        OrganizationMembership(
            user_id=owner_user_id,
            organization_id=organization.id,
            role="owner",
        )
    )
    session.commit()
    session.refresh(organization)
    return organization


def list_all_organizations(
    session: Session, limit: int, offset: int
) -> list[Organization]:
    statement = (
        select(Organization)
        .order_by(Organization.created_at, Organization.id)
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(statement))


def get_organization(session: Session, organization_id: UUID) -> Organization | None:
    return session.get(Organization, organization_id)


def get_organization_for_update(
    session: Session, organization_id: UUID
) -> Organization | None:
    statement = (
        select(Organization)
        .where(Organization.id == organization_id)
        .with_for_update()
    )
    return session.scalar(statement)


def list_organizations_for_user(
    session: Session, user_id: UUID, limit: int, offset: int
) -> list[Organization]:
    statement = (
        select(Organization)
        .join(
            OrganizationMembership,
            OrganizationMembership.organization_id == Organization.id,
        )
        .where(OrganizationMembership.user_id == user_id)
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
