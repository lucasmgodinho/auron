from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth.dependencies import get_current_user
from app.core.users import service
from app.core.users.model import User
from app.core.users.schemas import UserResponse, UserUpdate
from app.database import get_session

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    try:
        return service.get_own_user(session, user_id, current_user.id)
    except service.UserNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except service.UserAccessDeniedError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from error


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: UUID,
    payload: UserUpdate,
    session: Annotated[Session, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    try:
        return service.update_own_user(
            session,
            user_id,
            current_user.id,
            email=str(payload.email) if payload.email is not None else None,
            name=payload.name,
        )
    except service.UserNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    except service.UserEmailConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        ) from error
    except service.UserAccessDeniedError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from error
