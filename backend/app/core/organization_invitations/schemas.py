from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class OrganizationInvitationResponse(BaseModel):
    id: UUID
    organization_id: UUID
    organization_name: str
    expires_at: datetime
