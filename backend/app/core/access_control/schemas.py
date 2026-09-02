from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

AccessGroupName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]
AccessGroupDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=1000),
]


class AccessGroupCreate(BaseModel):
    name: AccessGroupName
    description: AccessGroupDescription | None = None

    model_config = ConfigDict(extra="forbid")


class AccessGroupUpdate(BaseModel):
    name: AccessGroupName | None = None
    description: AccessGroupDescription | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Name cannot be null")
        return self


class AccessGroupResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AccessGroupDetailResponse(AccessGroupResponse):
    permissions: list[str]
    membership_ids: list[UUID]


class PermissionReplace(BaseModel):
    permissions: list[str] = Field(max_length=500)

    model_config = ConfigDict(extra="forbid")


class MembershipReplace(BaseModel):
    membership_ids: list[UUID] = Field(max_length=500)

    model_config = ConfigDict(extra="forbid")


class PermissionDefinitionResponse(BaseModel):
    key: str
    resource: str
    action: str


class PermissionCatalogModuleResponse(BaseModel):
    key: str
    name_key: str
    enabled: bool
    permissions: list[PermissionDefinitionResponse]


class PermissionCatalogResponse(BaseModel):
    modules: list[PermissionCatalogModuleResponse]


class AccessSummaryResponse(BaseModel):
    is_owner: bool
    membership_role: Literal["owner", "admin", "member"]
    enabled_modules: list[str]
    permissions: list[str]
