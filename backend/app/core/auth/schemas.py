from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

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


class GenericMessageResponse(BaseModel):
    message: str
