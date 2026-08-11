from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.auth import service
from app.core.auth.dependencies import AUTH_SESSION_COOKIE_NAME, get_current_user
from app.core.users.model import User
from app.core.users.schemas import UserResponse
from app.database import get_session

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/me", response_model=UserResponse)
def get_authenticated_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
    raw_session_token: Annotated[
        str | None, Cookie(alias=AUTH_SESSION_COOKIE_NAME)
    ] = None,
) -> None:
    if raw_session_token is not None:
        service.revoke_session(session, raw_session_token)
    response.delete_cookie(
        AUTH_SESSION_COOKIE_NAME,
        path="/",
        secure=get_settings().auth_session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
