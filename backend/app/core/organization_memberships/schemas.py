from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

MembershipRole = Literal["owner", "admin", "member"]


class OrganizationMembershipCreate(BaseModel):
    user_id: UUID
    role: MembershipRole


class OrganizationMembershipUpdate(BaseModel):
    role: MembershipRole


class OrganizationMembershipResponse(BaseModel):
    id: UUID
    user_id: UUID
    organization_id: UUID
    role: MembershipRole
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
