from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApplicationEventResponse(BaseModel):
    id: UUID
    created_at: datetime
    level: str
    event: str
    category: str
    module: str | None
    request_id: str | None
    user_id: UUID | None
    user_name: str | None = None
    organization_id: UUID | None
    organization_name: str | None = None
    resource_type: str | None
    resource_id: str | None
    status: str | None
    duration_ms: int | None
    error_code: str | None
    error_message: str | None
    metadata: dict[str, str | int | bool | None] = Field(
        validation_alias="event_metadata"
    )

    model_config = ConfigDict(from_attributes=True)


class ApplicationEventPage(BaseModel):
    items: list[ApplicationEventResponse]
    total: int
    limit: int
    offset: int
