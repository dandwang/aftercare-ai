"""Administrator-only access to the current tenant's audit metadata."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aftercare_api.audit.models import AuditEvent
from aftercare_api.audit.schemas import AuditEventResponse
from aftercare_api.db.session import get_session
from aftercare_api.identity.dependencies import require_roles
from aftercare_api.identity.service import CurrentIdentity

router = APIRouter(prefix="/api/v1/audit-events", tags=["audit"])


@router.get("", response_model=list[AuditEventResponse])
async def list_audit_events(
    identity: Annotated[CurrentIdentity, Depends(require_roles("merchant_admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditEventResponse]:
    """Read only this tenant, regardless of any client-supplied tenant value."""

    events = await session.scalars(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == identity.tenant_id)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [AuditEventResponse.model_validate(event) for event in events]
