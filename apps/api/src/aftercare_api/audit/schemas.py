"""Public audit metadata without private content or credentials."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    actor_user_id: UUID
    actor_role: str
    action: str
    resource_type: str
    resource_id: UUID | None
    status_code: int
    result: str
    created_at: datetime
