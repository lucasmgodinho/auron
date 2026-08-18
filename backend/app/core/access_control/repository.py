from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.access_control.model import (
    OrganizationAccessGroup,
    OrganizationAccessGroupPermission,
    OrganizationMembershipAccessGroup,
)
from app.core.organization_memberships.model import OrganizationMembership


def add_access_group(
    session: Session,
    *,
    organization_id: UUID,
    name: str,
    description: str | None,
) -> OrganizationAccessGroup:
    group = OrganizationAccessGroup(
        organization_id=organization_id,
        name=name,
        description=description,
    )
    session.add(group)
    return group


def list_access_groups(
    session: Session, organization_id: UUID
) -> list[OrganizationAccessGroup]:
    return list(
        session.scalars(
            select(OrganizationAccessGroup)
            .where(OrganizationAccessGroup.organization_id == organization_id)
            .order_by(OrganizationAccessGroup.name, OrganizationAccessGroup.id)
        )
    )


def get_access_group(
    session: Session,
    *,
    organization_id: UUID,
    access_group_id: UUID,
    for_update: bool = False,
) -> OrganizationAccessGroup | None:
    statement = select(OrganizationAccessGroup).where(
        OrganizationAccessGroup.id == access_group_id,
        OrganizationAccessGroup.organization_id == organization_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def list_group_permission_keys(
    session: Session, access_group_id: UUID
) -> list[str]:
    return list(
        session.scalars(
            select(OrganizationAccessGroupPermission.permission_key)
            .where(
                OrganizationAccessGroupPermission.access_group_id == access_group_id
            )
            .order_by(OrganizationAccessGroupPermission.permission_key)
        )
    )


def list_group_membership_ids(
    session: Session, access_group_id: UUID
) -> list[UUID]:
    return list(
        session.scalars(
            select(OrganizationMembershipAccessGroup.organization_membership_id)
            .where(
                OrganizationMembershipAccessGroup.access_group_id == access_group_id
            )
            .order_by(
                OrganizationMembershipAccessGroup.organization_membership_id
            )
        )
    )


def replace_group_permissions(
    session: Session, *, access_group_id: UUID, permission_keys: Iterable[str]
) -> None:
    session.execute(
        delete(OrganizationAccessGroupPermission).where(
            OrganizationAccessGroupPermission.access_group_id == access_group_id
        )
    )
    session.add_all(
        OrganizationAccessGroupPermission(
            access_group_id=access_group_id,
            permission_key=permission_key,
        )
        for permission_key in permission_keys
    )


def get_memberships_in_organization(
    session: Session, *, organization_id: UUID, membership_ids: set[UUID]
) -> list[OrganizationMembership]:
    if not membership_ids:
        return []
    return list(
        session.scalars(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.id.in_(membership_ids),
            )
        )
    )


def replace_group_memberships(
    session: Session, *, access_group_id: UUID, membership_ids: Iterable[UUID]
) -> None:
    session.execute(
        delete(OrganizationMembershipAccessGroup).where(
            OrganizationMembershipAccessGroup.access_group_id == access_group_id
        )
    )
    session.add_all(
        OrganizationMembershipAccessGroup(
            organization_membership_id=membership_id,
            access_group_id=access_group_id,
        )
        for membership_id in membership_ids
    )


def list_membership_permission_keys(
    session: Session, *, organization_id: UUID, membership_id: UUID
) -> set[str]:
    statement = (
        select(OrganizationAccessGroupPermission.permission_key)
        .join(
            OrganizationMembershipAccessGroup,
            OrganizationMembershipAccessGroup.access_group_id
            == OrganizationAccessGroupPermission.access_group_id,
        )
        .join(
            OrganizationAccessGroup,
            OrganizationAccessGroup.id
            == OrganizationMembershipAccessGroup.access_group_id,
        )
        .where(
            OrganizationMembershipAccessGroup.organization_membership_id
            == membership_id,
            OrganizationAccessGroup.organization_id == organization_id,
        )
    )
    return set(session.scalars(statement))
