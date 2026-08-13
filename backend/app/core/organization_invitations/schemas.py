from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.users.schemas import NormalizedEmail

DEFAULT_INVITATION_TTL_HOURS = 168


class OrganizationInvitationResponse(BaseModel):
    id: UUID
    organization_id: UUID
    organization_name: str
    expires_at: datetime


class OrganizationInvitationReissue(BaseModel):
    email: NormalizedEmail
    expires_hours: int = Field(default=DEFAULT_INVITATION_TTL_HOURS, gt=0)

    model_config = ConfigDict(extra="forbid")
