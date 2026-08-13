from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth.dependencies import get_current_user
from app.core.platform_admin import repository
from app.core.platform_admin.model import PlatformAdmin
from app.core.users.model import User
from app.database import get_session


def get_current_platform_admin(
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PlatformAdmin:
    platform_admin = repository.get_platform_admin_by_user_id(session, current_user.id)
    if platform_admin is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform Admin access required",
        )
    return platform_admin
