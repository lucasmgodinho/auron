from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.application_events.service import record_event
from app.core.auth.dependencies import get_current_user
from app.core.organization_invitations import service
from app.core.organization_invitations.schemas import OrganizationInvitationResponse
from app.core.organizations.model import Organization
from app.core.organizations.schemas import OrganizationResponse
from app.core.users.model import User
from app.database import get_session

router = APIRouter(
    prefix="/organization-invitations",
    tags=["organization-invitations"],
)


@router.get("/me", response_model=list[OrganizationInvitationResponse])
def list_current_user_invitations(
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[OrganizationInvitationResponse]:
    return service.list_pending_invitations(session, current_user)


@router.post("/{invitation_id}/accept", response_model=OrganizationResponse)
def accept_invitation(
    invitation_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Organization:
    try:
        organization = service.accept_invitation(
            session,
            invitation_id=invitation_id,
            current_user=current_user,
        )
    except service.OrganizationInvitationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except service.OrganizationInvitationExpiredError as error:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Invitation has expired",
        ) from error
    except service.OrganizationInvitationAcceptedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invitation has already been accepted",
        ) from error
    except service.OrganizationInvitationEmailMismatchError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from error
    except service.OrganizationInvitationEmailUnverifiedError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verified email required",
        ) from error
    record_event(
        level="info",
        event="organization.member.joined",
        category="organization",
        user_id=current_user.id,
        organization_id=organization.id,
        resource_type="organization_invitation",
        resource_id=invitation_id,
        status="succeeded",
    )
    return organization
