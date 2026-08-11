from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.organization_memberships import service
from app.core.organization_memberships.model import OrganizationMembership
from app.core.organization_memberships.schemas import (
    OrganizationMembershipCreate,
    OrganizationMembershipResponse,
    OrganizationMembershipUpdate,
)
from app.core.organizations import service as organization_service
from app.core.users import service as user_service
from app.database import get_session

router = APIRouter(tags=["organization memberships"])


@router.post(
    "/organizations/{organization_id}/memberships",
    response_model=OrganizationMembershipResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_membership(
    organization_id: UUID,
    payload: OrganizationMembershipCreate,
    session: Annotated[Session, Depends(get_session)],
) -> OrganizationMembership:
    try:
        return service.create_membership(
            session,
            organization_id=organization_id,
            user_id=payload.user_id,
            role=payload.role,
        )
    except organization_service.OrganizationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except user_service.UserNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except service.MembershipConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This user is already a member of the organization",
        ) from error


@router.get(
    "/organizations/{organization_id}/memberships",
    response_model=list[OrganizationMembershipResponse],
)
def list_organization_memberships(
    organization_id: UUID,
    session: Annotated[Session, Depends(get_session)],
) -> list[OrganizationMembership]:
    try:
        return service.list_organization_memberships(session, organization_id)
    except organization_service.OrganizationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error


@router.get(
    "/users/{user_id}/memberships",
    response_model=list[OrganizationMembershipResponse],
)
def list_user_memberships(
    user_id: UUID,
    session: Annotated[Session, Depends(get_session)],
) -> list[OrganizationMembership]:
    try:
        return service.list_user_memberships(session, user_id)
    except user_service.UserNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error


@router.patch(
    "/organizations/{organization_id}/memberships/{membership_id}",
    response_model=OrganizationMembershipResponse,
)
def update_membership(
    organization_id: UUID,
    membership_id: UUID,
    payload: OrganizationMembershipUpdate,
    session: Annotated[Session, Depends(get_session)],
) -> OrganizationMembership:
    try:
        return service.update_membership_role(
            session,
            organization_id=organization_id,
            membership_id=membership_id,
            role=payload.role,
        )
    except organization_service.OrganizationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except service.MembershipNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
