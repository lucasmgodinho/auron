from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    StringConstraints,
)


def _normalize_email(value: object) -> object:
    if isinstance(value, str):
        return value.strip().lower()
    return value


UserName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
NormalizedEmail = Annotated[EmailStr, BeforeValidator(_normalize_email)]


class UserCreate(BaseModel):
    email: NormalizedEmail
    name: UserName


class UserUpdate(BaseModel):
    name: UserName

    model_config = ConfigDict(extra="forbid")


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    name: str
    email_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
