from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    StringConstraints,
    model_validator,
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
    email: NormalizedEmail | None = None
    name: UserName | None = None

    @model_validator(mode="after")
    def require_non_null_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("User fields cannot be null")
        return self


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    name: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
