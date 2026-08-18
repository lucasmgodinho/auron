from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.module_registry.dependencies import get_module_registry
from app.core.module_registry.registry import ModuleRegistry
from app.core.organization_context.context import OrganizationContext
from app.core.organization_context.dependencies import get_organization_context
from app.core.organization_modules import service
from app.core.organization_modules.schemas import ModuleResponse
from app.database import get_session

router = APIRouter(tags=["organization modules"])


@router.get(
    "/organizations/{organization_id}/modules",
    response_model=list[ModuleResponse],
)
def list_enabled_organization_modules(
    session: Annotated[Session, Depends(get_session)],
    context: Annotated[OrganizationContext, Depends(get_organization_context)],
    registry: Annotated[ModuleRegistry, Depends(get_module_registry)],
) -> list[ModuleResponse]:
    definitions = service.list_enabled_modules(
        session,
        organization_id=context.organization.id,
        registry=registry,
    )
    return [ModuleResponse(key=item.key, name_key=item.name_key) for item in definitions]
