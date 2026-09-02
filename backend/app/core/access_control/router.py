from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.access_control import service
from app.core.access_control.dependencies import get_owner_organization_context
from app.core.access_control.model import OrganizationAccessGroup
from app.core.access_control.schemas import (
    AccessGroupCreate,
    AccessGroupDetailResponse,
    AccessGroupResponse,
    AccessGroupUpdate,
    AccessSummaryResponse,
    MembershipReplace,
    PermissionCatalogModuleResponse,
    PermissionCatalogResponse,
    PermissionDefinitionResponse,
    PermissionReplace,
)
from app.core.application_events.service import record_event
from app.core.module_registry.dependencies import get_module_registry
from app.core.module_registry.registry import ModuleRegistry
from app.core.organization_context.context import OrganizationContext
from app.core.organization_context.dependencies import get_organization_context
from app.database import get_session

router = APIRouter(tags=["access control"])


def _detail_response(details: service.AccessGroupDetails) -> AccessGroupDetailResponse:
    return AccessGroupDetailResponse(
        **AccessGroupResponse.model_validate(details.group).model_dump(),
        permissions=details.permission_keys,
        membership_ids=details.membership_ids,
    )


@router.get(
    "/organizations/{organization_id}/access-groups",
    response_model=list[AccessGroupResponse],
)
def list_access_groups(
    session: Annotated[Session, Depends(get_session)],
    context: Annotated[
        OrganizationContext, Depends(get_owner_organization_context)
    ],
) -> list[OrganizationAccessGroup]:
    return service.list_access_groups(session, context.organization.id)


@router.post(
    "/organizations/{organization_id}/access-groups",
    response_model=AccessGroupResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_access_group(
    payload: AccessGroupCreate,
    session: Annotated[Session, Depends(get_session)],
    context: Annotated[
        OrganizationContext, Depends(get_owner_organization_context)
    ],
) -> OrganizationAccessGroup:
    try:
        return service.create_access_group(
            session,
            organization_id=context.organization.id,
            name=payload.name,
            description=payload.description,
        )
    except service.AccessGroupConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An access group with this name already exists",
        ) from error


@router.get(
    "/organizations/{organization_id}/access-groups/{access_group_id}",
    response_model=AccessGroupDetailResponse,
)
def get_access_group(
    access_group_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    context: Annotated[
        OrganizationContext, Depends(get_owner_organization_context)
    ],
) -> AccessGroupDetailResponse:
    try:
        return _detail_response(
            service.get_access_group_details(
                session,
                organization_id=context.organization.id,
                access_group_id=access_group_id,
            )
        )
    except service.AccessGroupNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error


@router.patch(
    "/organizations/{organization_id}/access-groups/{access_group_id}",
    response_model=AccessGroupResponse,
)
def update_access_group(
    access_group_id: UUID,
    payload: AccessGroupUpdate,
    session: Annotated[Session, Depends(get_session)],
    context: Annotated[
        OrganizationContext, Depends(get_owner_organization_context)
    ],
) -> OrganizationAccessGroup:
    try:
        return service.update_access_group(
            session,
            organization_id=context.organization.id,
            access_group_id=access_group_id,
            name=payload.name,
            description=payload.description,
            description_is_set="description" in payload.model_fields_set,
        )
    except service.AccessGroupNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except service.AccessGroupConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An access group with this name already exists",
        ) from error


@router.delete(
    "/organizations/{organization_id}/access-groups/{access_group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_access_group(
    access_group_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    context: Annotated[
        OrganizationContext, Depends(get_owner_organization_context)
    ],
) -> Response:
    try:
        service.delete_access_group(
            session,
            organization_id=context.organization.id,
            access_group_id=access_group_id,
        )
    except service.AccessGroupNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/organizations/{organization_id}/access-groups/{access_group_id}/permissions",
    response_model=AccessGroupDetailResponse,
)
def replace_access_group_permissions(
    access_group_id: UUID,
    payload: PermissionReplace,
    session: Annotated[Session, Depends(get_session)],
    context: Annotated[
        OrganizationContext, Depends(get_owner_organization_context)
    ],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
) -> AccessGroupDetailResponse:
    try:
        details = _detail_response(
            service.replace_access_group_permissions(
                session,
                organization_id=context.organization.id,
                access_group_id=access_group_id,
                permission_keys=payload.permissions,
                registry=registry,
            )
        )
    except service.AccessGroupNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except service.InvalidPermissionError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="One or more permission keys are invalid",
        ) from error
    record_event(
        level="info",
        event="access.permissions.changed",
        category="access",
        organization_id=context.organization.id,
        resource_type="organization_access_group",
        resource_id=access_group_id,
        status="succeeded",
        metadata={"permission_count": len(details.permissions)},
    )
    return details


@router.put(
    "/organizations/{organization_id}/access-groups/{access_group_id}/memberships",
    response_model=AccessGroupDetailResponse,
)
def replace_access_group_memberships(
    access_group_id: UUID,
    payload: MembershipReplace,
    session: Annotated[Session, Depends(get_session)],
    context: Annotated[
        OrganizationContext, Depends(get_owner_organization_context)
    ],
) -> AccessGroupDetailResponse:
    try:
        details = _detail_response(
            service.replace_access_group_memberships(
                session,
                organization_id=context.organization.id,
                access_group_id=access_group_id,
                membership_ids=payload.membership_ids,
            )
        )
    except (
        service.AccessGroupNotFoundError,
        service.MembershipAssignmentError,
    ) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    record_event(
        level="info",
        event="access.group.memberships_changed",
        category="access",
        organization_id=context.organization.id,
        resource_type="organization_access_group",
        resource_id=access_group_id,
        status="succeeded",
        metadata={"membership_count": len(details.membership_ids)},
    )
    return details


@router.get(
    "/organizations/{organization_id}/access-control/permission-catalog",
    response_model=PermissionCatalogResponse,
)
def get_permission_catalog(
    session: Annotated[Session, Depends(get_session)],
    context: Annotated[
        OrganizationContext, Depends(get_owner_organization_context)
    ],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
) -> PermissionCatalogResponse:
    modules = service.list_permission_catalog(
        session,
        organization_id=context.organization.id,
        registry=registry,
    )
    return PermissionCatalogResponse(
        modules=[
            PermissionCatalogModuleResponse(
                key=definition.key,
                name_key=definition.name_key,
                enabled=enabled,
                permissions=[
                    PermissionDefinitionResponse(
                        key=permission.key,
                        resource=permission.resource,
                        action=permission.action,
                    )
                    for permission in definition.permissions
                ],
            )
            for definition, enabled in modules
        ]
    )


@router.get(
    "/organizations/{organization_id}/access-control/me",
    response_model=AccessSummaryResponse,
)
def get_access_summary(
    session: Annotated[Session, Depends(get_session)],
    context: Annotated[OrganizationContext, Depends(get_organization_context)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
) -> AccessSummaryResponse:
    access = service.get_effective_access(
        session,
        context=context,
        registry=registry,
    )
    return AccessSummaryResponse(
        is_owner=access.is_owner,
        membership_role=context.membership.role,
        enabled_modules=list(access.enabled_module_keys),
        permissions=list(access.permission_keys),
    )
