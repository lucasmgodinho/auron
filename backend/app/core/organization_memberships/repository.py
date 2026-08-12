from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.organization_memberships.model import OrganizationMembership


def create_membership(
    session: Session,
    *,
    user_id: UUID,
    organization_id: UUID,
    role: str,
) -> OrganizationMembership:
    membership = OrganizationMembership(
        user_id=user_id,
        organization_id=organization_id,
        role=role,
    )
    session.add(membership)
    session.commit()
    session.refresh(membership)
    return membership


def get_membership(
    session: Session,
    *,
    membership_id: UUID,
    organization_id: UUID,
) -> OrganizationMembership | None:
    statement = select(OrganizationMembership).where(
        OrganizationMembership.id == membership_id,
        OrganizationMembership.organization_id == organization_id,
    )
    return session.scalar(statement)


def get_membership_for_user_organization(
    session: Session, *, user_id: UUID, organization_id: UUID
) -> OrganizationMembership | None:
    statement = select(OrganizationMembership).where(
        OrganizationMembership.user_id == user_id,
        OrganizationMembership.organization_id == organization_id,
    )
    return session.scalar(statement)


def count_organization_owners(session: Session, organization_id: UUID) -> int:
    statement = select(func.count()).select_from(OrganizationMembership).where(
        OrganizationMembership.organization_id == organization_id,
        OrganizationMembership.role == "owner",
    )
    return session.scalar(statement) or 0


def list_organization_memberships(
    session: Session, organization_id: UUID
) -> list[OrganizationMembership]:
    statement = (
        select(OrganizationMembership)
        .where(OrganizationMembership.organization_id == organization_id)
        .order_by(OrganizationMembership.created_at, OrganizationMembership.id)
    )
    return list(session.scalars(statement))


def list_user_memberships(
    session: Session, user_id: UUID
) -> list[OrganizationMembership]:
    statement = (
        select(OrganizationMembership)
        .where(OrganizationMembership.user_id == user_id)
        .order_by(OrganizationMembership.created_at, OrganizationMembership.id)
    )
    return list(session.scalars(statement))


def update_membership_role(
    session: Session,
    membership: OrganizationMembership,
    role: str,
) -> OrganizationMembership:
    membership.role = role
    session.commit()
    session.refresh(membership)
    return membership
