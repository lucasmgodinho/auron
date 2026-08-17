from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, StringConstraints

from app.core.users.schemas import NormalizedEmail, UserName

Password = Annotated[str, StringConstraints(min_length=10, max_length=256)]
VerificationToken = Annotated[str, StringConstraints(min_length=1, max_length=512)]


class RegistrationRequest(BaseModel):
    name: UserName
    email: NormalizedEmail

    model_config = ConfigDict(extra="forbid")


class EmailVerificationResendRequest(BaseModel):
    email: NormalizedEmail

    model_config = ConfigDict(extra="forbid")


class EmailVerificationCompleteRequest(BaseModel):
    token: VerificationToken
    password: Password

    model_config = ConfigDict(extra="forbid")


class PasswordLoginRequest(BaseModel):
    email: NormalizedEmail
    password: Annotated[str, StringConstraints(min_length=1, max_length=256)]

    model_config = ConfigDict(extra="forbid")


class PasswordChangeRequest(BaseModel):
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    new_password: Password

    model_config = ConfigDict(extra="forbid")


class AccountUserResponse(BaseModel):
    id: UUID
    email: EmailStr
    name: str
    email_verified_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class AuthenticationMethodsResponse(BaseModel):
    password: bool
    google: bool


class AccountResponse(BaseModel):
    user: AccountUserResponse
    authentication_methods: AuthenticationMethodsResponse


class GenericMessageResponse(BaseModel):
    message: str
