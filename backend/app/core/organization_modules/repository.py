from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.organization_modules.model import OrganizationModule


def get_organization_module(
    session: Session, *, organization_id: UUID, module_key: str
) -> OrganizationModule | None:
    return session.scalar(
        select(OrganizationModule).where(
            OrganizationModule.organization_id == organization_id,
            OrganizationModule.module_key == module_key,
        )
    )


def list_organization_modules(
    session: Session, organization_id: UUID
) -> list[OrganizationModule]:
    return list(
        session.scalars(
            select(OrganizationModule).where(
                OrganizationModule.organization_id == organization_id
            )
        )
    )


def list_enabled_module_keys(session: Session, organization_id: UUID) -> set[str]:
    return set(
        session.scalars(
            select(OrganizationModule.module_key).where(
                OrganizationModule.organization_id == organization_id,
                OrganizationModule.enabled.is_(True),
            )
        )
    )


def add_organization_module(
    session: Session, *, organization_id: UUID, module_key: str, enabled: bool
) -> OrganizationModule:
    entitlement = OrganizationModule(
        organization_id=organization_id,
        module_key=module_key,
        enabled=enabled,
    )
    session.add(entitlement)
    return entitlement
