from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.access_control import service
from app.core.module_registry.definitions import ModuleDefinition, PermissionDefinition
from app.core.module_registry.dependencies import get_module_registry
from app.core.module_registry.registry import (
    ModuleRegistry,
    validate_identifier,
)
from app.core.organization_context.context import OrganizationContext
from app.core.organization_context.dependencies import get_organization_context
from app.core.organization_modules import service as module_service
from app.database import get_session


@dataclass(frozen=True, slots=True)
class ModuleAccessContext:
    organization_context: OrganizationContext
    module: ModuleDefinition
    permission: PermissionDefinition


def get_owner_organization_context(
    context: Annotated[OrganizationContext, Depends(get_organization_context)],
) -> OrganizationContext:
    if context.membership.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return context


def require_module_permission(
    *, module_key: str, permission_key: str
) -> Callable[..., ModuleAccessContext]:
    validate_identifier(module_key, "module key")
    parts = permission_key.split(".")
    if len(parts) != 3 or parts[0] != module_key:
        raise ValueError(
            "Permission key must use the requested module namespace"
        )
    validate_identifier(parts[1], "permission resource")
    validate_identifier(parts[2], "permission action")

    def dependency(
        context: Annotated[
            OrganizationContext, Depends(get_organization_context)
        ],
        session: Annotated[Session, Depends(get_session)],
        registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
    ) -> ModuleAccessContext:
        module = registry.get(module_key)
        permission = registry.get_permission(permission_key)
        if module is None or permission is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        if not module_service.is_module_enabled(
            session,
            organization_id=context.organization.id,
            module_key=module_key,
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        if context.membership.role != "owner":
            access = service.get_effective_access(
                session,
                context=context,
                registry=registry,
            )
            if permission_key not in access.permission_keys:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return ModuleAccessContext(
            organization_context=context,
            module=module,
            permission=permission,
        )

    return dependency
