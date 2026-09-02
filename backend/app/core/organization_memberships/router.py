from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.application_events.service import record_event
from app.core.auth.dependencies import get_current_user
from app.core.organization_context.context import OrganizationContext
from app.core.organization_context.dependencies import get_organization_context
from app.core.organization_memberships import service
from app.core.organization_memberships.model import OrganizationMembership
from app.core.organization_memberships.schemas import (
    OrganizationMembershipCreate,
    OrganizationMembershipResponse,
    OrganizationMembershipUpdate,
)
from app.core.organizations import service as organization_service
from app.core.users import service as user_service
from app.core.users.model import User
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
    current_user: Annotated[User, Depends(get_current_user)],
) -> OrganizationMembership:
    try:
        membership = service.create_membership(
            session,
            organization_id=organization_id,
            user_id=payload.user_id,
            role=payload.role,
            current_user_id=current_user.id,
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
    except service.MembershipAccessDeniedError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from error
    record_event(
        level="info",
        event="organization.member.added",
        category="organization",
        user_id=current_user.id,
        organization_id=organization_id,
        resource_type="organization_membership",
        resource_id=membership.id,
        status="succeeded",
        metadata={"new_role": membership.role},
    )
    return membership


@router.get(
    "/organizations/{organization_id}/memberships",
    response_model=list[OrganizationMembershipResponse],
)
def list_organization_memberships(
    session: Annotated[Session, Depends(get_session)],
    context: Annotated[OrganizationContext, Depends(get_organization_context)],
) -> list[OrganizationMembership]:
    return service.list_organization_memberships(session, context.organization.id)


@router.get(
    "/users/{user_id}/memberships",
    response_model=list[OrganizationMembershipResponse],
)
def list_user_memberships(
    user_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[OrganizationMembership]:
    try:
        return service.list_user_memberships(session, user_id, current_user.id)
    except user_service.UserNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except service.MembershipAccessDeniedError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from error


@router.patch(
    "/organizations/{organization_id}/memberships/{membership_id}",
    response_model=OrganizationMembershipResponse,
)
def update_membership(
    organization_id: UUID,
    membership_id: UUID,
    payload: OrganizationMembershipUpdate,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> OrganizationMembership:
    try:
        membership = service.update_membership_role(
            session,
            organization_id=organization_id,
            membership_id=membership_id,
            role=payload.role,
            current_user_id=current_user.id,
        )
    except organization_service.OrganizationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except service.MembershipNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except service.MembershipAccessDeniedError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from error
    except service.LastOwnerError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An organization must have at least one owner",
        ) from error
    record_event(
        level="info",
        event="organization.member.role_changed",
        category="organization",
        user_id=current_user.id,
        organization_id=organization_id,
        resource_type="organization_membership",
        resource_id=membership.id,
        status="succeeded",
        metadata={"new_role": membership.role},
    )
    return membership
