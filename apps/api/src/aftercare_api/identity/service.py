"""Application services for registration, login, and authenticated identity."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aftercare_api.identity.models import Tenant, TenantMembership, User
from aftercare_api.identity.schemas import RegisterTenantAdminRequest
from aftercare_api.identity.security import hash_password, verify_password


class RegistrationConflictError(Exception):
    """Raised when a tenant slug or user email is already registered."""


class AuthenticationFailedError(Exception):
    """Raised when a login cannot establish an active identity."""


@dataclass(frozen=True)
class CurrentIdentity:
    """Server-verified identity context for a protected request."""

    user_id: UUID
    email: str
    tenant_id: UUID
    tenant_name: str
    role: str


async def register_tenant_admin(
    session: AsyncSession,
    payload: RegisterTenantAdminRequest,
) -> User:
    """Create tenant, user, and initial membership atomically."""

    tenant = Tenant(name=payload.tenant_name.strip(), slug=payload.tenant_slug)
    user = User(email=payload.email, password_hash=hash_password(payload.password))
    try:
        async with session.begin():
            session.add_all((tenant, user))
            await session.flush()
            session.add(
                TenantMembership(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    role="merchant_admin",
                )
            )
            await session.flush()
    except IntegrityError as error:
        raise RegistrationConflictError from error
    return user


async def authenticate(
    session: AsyncSession,
    email: str,
    password: str,
) -> User:
    """Validate credentials and require at least one active tenant membership."""

    statement = (
        select(User)
        .join(TenantMembership, TenantMembership.user_id == User.id)
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .where(
            User.email == email,
            User.is_active.is_(True),
            TenantMembership.is_active.is_(True),
            Tenant.is_active.is_(True),
        )
    )
    user = (await session.execute(statement)).scalars().first()
    if user is None or not verify_password(password, user.password_hash):
        raise AuthenticationFailedError
    return user


async def get_current_identity(session: AsyncSession, user_id: UUID) -> CurrentIdentity:
    """Recheck user, tenant, and membership status for every protected request."""

    statement = (
        select(User, TenantMembership, Tenant)
        .join(TenantMembership, TenantMembership.user_id == User.id)
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .where(
            User.id == user_id,
            User.is_active.is_(True),
            TenantMembership.is_active.is_(True),
            Tenant.is_active.is_(True),
        )
        .order_by(TenantMembership.created_at)
    )
    row = (await session.execute(statement)).first()
    if row is None:
        raise AuthenticationFailedError
    user, membership, tenant = row
    return CurrentIdentity(
        user_id=user.id,
        email=user.email,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        role=membership.role,
    )
