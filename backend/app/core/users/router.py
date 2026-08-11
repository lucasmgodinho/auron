from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.users import service
from app.core.users.model import User
from app.core.users.schemas import UserCreate, UserResponse, UserUpdate
from app.database import get_session

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    session: Annotated[Session, Depends(get_session)],
) -> User:
    try:
        return service.create_user(session, email=str(payload.email), name=payload.name)
    except service.UserEmailConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        ) from error


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: UUID,
    session: Annotated[Session, Depends(get_session)],
) -> User:
    try:
        return service.get_user(session, user_id)
    except service.UserNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error


@router.get("", response_model=list[UserResponse])
def list_users(
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[User]:
    return service.list_users(session, limit, offset)


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: UUID,
    payload: UserUpdate,
    session: Annotated[Session, Depends(get_session)],
) -> User:
    try:
        return service.update_user(
            session,
            user_id,
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
