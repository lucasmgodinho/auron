from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

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
