from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.application_events.context import bind_application_event_organization
from app.core.auth.dependencies import get_current_user
from app.core.organization_context.context import OrganizationContext
from app.core.organization_memberships import repository as membership_repository
from app.core.organizations import repository as organization_repository
from app.core.users.model import User
from app.database import get_session


def get_organization_context(
    organization_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> OrganizationContext:
    organization = organization_repository.get_organization(session, organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    membership = membership_repository.get_membership_for_user_organization(
        session,
        user_id=current_user.id,
        organization_id=organization.id,
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    bind_application_event_organization(organization.id)
    return OrganizationContext(
        user=current_user,
        organization=organization,
        membership=membership,
    )
