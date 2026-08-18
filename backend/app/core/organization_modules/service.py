from uuid import UUID

from sqlalchemy.orm import Session

from app.core.module_registry.definitions import ModuleDefinition
from app.core.module_registry.registry import ModuleRegistry
from app.core.organization_modules import repository
from app.core.organizations import repository as organization_repository
from app.core.organizations import service as organization_service


class ModuleNotFoundError(Exception):
    pass


def list_registered_modules(registry: ModuleRegistry) -> tuple[ModuleDefinition, ...]:
    return registry.list()


def list_organization_module_configuration(
    session: Session, *, organization_id: UUID, registry: ModuleRegistry
) -> list[tuple[ModuleDefinition, bool]]:
    if organization_repository.get_organization(session, organization_id) is None:
        raise organization_service.OrganizationNotFoundError
    entitlements = {
        entitlement.module_key: entitlement.enabled
        for entitlement in repository.list_organization_modules(
            session, organization_id
        )
    }
    return [
        (definition, entitlements.get(definition.key, False))
        for definition in registry.list()
    ]


def set_organization_module(
    session: Session,
    *,
    organization_id: UUID,
    module_key: str,
    enabled: bool,
    registry: ModuleRegistry,
) -> tuple[ModuleDefinition, bool]:
    try:
        organization_service.get_organization_for_update(session, organization_id)
        definition = registry.get(module_key)
        if definition is None:
            raise ModuleNotFoundError

        entitlement = repository.get_organization_module(
            session,
            organization_id=organization_id,
            module_key=module_key,
        )
        if entitlement is None:
            entitlement = repository.add_organization_module(
                session,
                organization_id=organization_id,
                module_key=module_key,
                enabled=enabled,
            )
        else:
            entitlement.enabled = enabled
        session.commit()
        return definition, enabled
    except Exception:
        session.rollback()
        raise


def list_enabled_modules(
    session: Session, *, organization_id: UUID, registry: ModuleRegistry
) -> list[ModuleDefinition]:
    enabled_keys = repository.list_enabled_module_keys(session, organization_id)
    return [definition for definition in registry.list() if definition.key in enabled_keys]


def is_module_enabled(
    session: Session, *, organization_id: UUID, module_key: str
) -> bool:
    entitlement = repository.get_organization_module(
        session,
        organization_id=organization_id,
        module_key=module_key,
    )
    return entitlement is not None and entitlement.enabled
