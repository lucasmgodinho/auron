from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth.dependencies import get_current_user
from app.core.organizations import service
from app.core.organizations.model import Organization
from app.core.organizations.schemas import (
    OrganizationCreate,
    OrganizationResponse,
    OrganizationUpdate,
)
from app.core.users.model import User
from app.database import get_session

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrganizationCreate,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Organization:
    return service.create_organization(session, payload.name, current_user.id)


@router.get("/{organization_id}", response_model=OrganizationResponse)
def get_organization(
    organization_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Organization:
    try:
        return service.get_organization_for_user(
            session, organization_id, current_user.id
        )
    except service.OrganizationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except service.OrganizationAccessDeniedError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from error


@router.get("", response_model=list[OrganizationResponse])
def list_organizations(
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Organization]:
    return service.list_organizations_for_user(
        session, current_user.id, limit, offset
    )


@router.patch("/{organization_id}", response_model=OrganizationResponse)
def update_organization(
    organization_id: UUID,
    payload: OrganizationUpdate,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Organization:
    try:
        return service.update_organization_name(
            session, organization_id, current_user.id, payload.name
        )
    except service.OrganizationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except service.OrganizationAccessDeniedError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from error
