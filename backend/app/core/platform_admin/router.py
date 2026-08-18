from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.module_registry.dependencies import get_module_registry
from app.core.module_registry.registry import ModuleRegistry
from app.core.organization_modules import service as module_service
from app.core.organization_modules.schemas import (
    ModuleResponse,
    OrganizationModuleResponse,
    OrganizationModuleUpdate,
)
from app.core.organizations import service as organization_service
from app.core.organizations.model import Organization
from app.core.organizations.schemas import OrganizationResponse
from app.core.platform_admin import service
from app.core.platform_admin.dependencies import get_current_platform_admin
from app.core.platform_admin.model import PlatformAdmin
from app.core.platform_admin.schemas import (
    PlatformAdminStatus,
    PlatformOrganizationCreate,
)
from app.database import get_session

router = APIRouter(prefix="/platform-admin", tags=["platform-admin"])


@router.get("/me", response_model=PlatformAdminStatus)
def get_platform_admin_status(
    _: Annotated[PlatformAdmin, Depends(get_current_platform_admin)],
) -> PlatformAdminStatus:
    return PlatformAdminStatus()


@router.get("/organizations", response_model=list[OrganizationResponse])
def list_organizations(
    session: Annotated[Session, Depends(get_session)],
    _: Annotated[PlatformAdmin, Depends(get_current_platform_admin)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Organization]:
    return service.list_organizations(session, limit=limit, offset=offset)


@router.post(
    "/organizations",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_organization(
    payload: PlatformOrganizationCreate,
    session: Annotated[Session, Depends(get_session)],
    _: Annotated[PlatformAdmin, Depends(get_current_platform_admin)],
) -> Organization:
    return service.provision_organization(session, payload)


@router.get("/modules", response_model=list[ModuleResponse])
def list_modules(
    _: Annotated[PlatformAdmin, Depends(get_current_platform_admin)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
) -> list[ModuleResponse]:
    return [
        ModuleResponse(key=definition.key, name_key=definition.name_key)
        for definition in module_service.list_registered_modules(registry)
    ]


@router.get(
    "/organizations/{organization_id}/modules",
    response_model=list[OrganizationModuleResponse],
)
def list_organization_modules(
    organization_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    _: Annotated[PlatformAdmin, Depends(get_current_platform_admin)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
) -> list[OrganizationModuleResponse]:
    try:
        configuration = module_service.list_organization_module_configuration(
            session,
            organization_id=organization_id,
            registry=registry,
        )
    except organization_service.OrganizationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    return [
        OrganizationModuleResponse(
            key=definition.key,
            name_key=definition.name_key,
            enabled=enabled,
        )
        for definition, enabled in configuration
    ]


@router.put(
    "/organizations/{organization_id}/modules/{module_key}",
    response_model=OrganizationModuleResponse,
)
def update_organization_module(
    organization_id: UUID,
    module_key: str,
    payload: OrganizationModuleUpdate,
    session: Annotated[Session, Depends(get_session)],
    _: Annotated[PlatformAdmin, Depends(get_current_platform_admin)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
) -> OrganizationModuleResponse:
    try:
        definition, enabled = module_service.set_organization_module(
            session,
            organization_id=organization_id,
            module_key=module_key,
            enabled=payload.enabled,
            registry=registry,
        )
    except organization_service.OrganizationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except module_service.ModuleNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    return OrganizationModuleResponse(
        key=definition.key,
        name_key=definition.name_key,
        enabled=enabled,
    )
