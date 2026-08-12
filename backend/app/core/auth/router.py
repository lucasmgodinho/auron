from typing import Annotated

from authlib.integrations.base_client import OAuthError
from authlib.oidc.core import UserInfo
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from httpx import HTTPError
from joserfc.errors import JoseError
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse

from app.config import get_settings
from app.core.auth import google, service
from app.core.auth.dependencies import (
    AUTH_SESSION_COOKIE_NAME,
    clear_auth_session_cookie,
    get_current_user,
    set_auth_session_cookie,
)
from app.core.users.model import User
from app.core.users.schemas import UserResponse
from app.database import get_session

router = APIRouter(prefix="/auth", tags=["authentication"])
GOOGLE_NOT_CONFIGURED_DETAIL = "Google authentication is not configured."


def _get_google_oauth_client():
    if google.google_oauth_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=GOOGLE_NOT_CONFIGURED_DETAIL,
        )
    return google.google_oauth_client


@router.get("/google/login")
async def google_login(request: Request) -> Response:
    google_oauth_client = _get_google_oauth_client()
    redirect_uri = get_settings().google_redirect_uri
    assert redirect_uri is not None
    return await google_oauth_client.authorize_redirect(
        request,
        str(redirect_uri),
    )


@router.get("/google/callback")
async def google_callback(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    google_oauth_client = _get_google_oauth_client()
    try:
        token = await google_oauth_client.authorize_access_token(request)
    except (HTTPError, JoseError, OAuthError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google authentication failed",
        ) from error

    claims = token.get("userinfo")
    if not isinstance(claims, UserInfo):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google authentication failed",
        )

    try:
        user = google.resolve_google_user(session, claims)
    except google.GoogleAuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google authentication failed",
        ) from error

    _, raw_session_token = service.create_auth_session(session, user.id)
    success_redirect_url = get_settings().auth_login_success_redirect_url
    assert success_redirect_url is not None
    response = RedirectResponse(
        str(success_redirect_url),
        status_code=status.HTTP_302_FOUND,
    )
    set_auth_session_cookie(response, raw_session_token)
    return response


@router.get("/me", response_model=UserResponse)
def get_authenticated_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    raw_session_token: Annotated[
        str | None, Cookie(alias=AUTH_SESSION_COOKIE_NAME)
    ] = None,
) -> None:
    if raw_session_token is not None:
        service.revoke_session(session, raw_session_token)
    clear_auth_session_cookie(response)
