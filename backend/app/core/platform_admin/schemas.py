from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.core.users.schemas import NormalizedEmail


class PlatformAdminStatus(BaseModel):
    is_platform_admin: Literal[True] = True


class PlatformAdminGrant(BaseModel):
    email: NormalizedEmail

    model_config = ConfigDict(extra="forbid")


class PlatformOrganizationCreate(BaseModel):
    name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
    ]
    invitation_emails: list[NormalizedEmail] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")

    @field_validator("invitation_emails", mode="after")
    @classmethod
    def deduplicate_emails(cls, emails: list[NormalizedEmail]) -> list[NormalizedEmail]:
        return list(dict.fromkeys(emails))
