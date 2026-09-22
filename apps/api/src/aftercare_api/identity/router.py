"""HTTP endpoints for tenant administrator authentication."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from aftercare_api.config import Settings, get_settings
from aftercare_api.db.session import get_session
from aftercare_api.identity.dependencies import require_current_identity
from aftercare_api.identity.schemas import (
    AccessTokenResponse,
    CurrentUserResponse,
    LoginRequest,
    RegisterTenantAdminRequest,
)
from aftercare_api.identity.security import create_access_token
from aftercare_api.identity.service import (
    AuthenticationFailedError,
    CurrentIdentity,
    RegistrationConflictError,
    authenticate,
    register_tenant_admin,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def token_response(user_id: UUID, settings: Settings) -> AccessTokenResponse:
    """Build the standard access-token response for an authenticated user."""

    token, expires_in = create_access_token(user_id, settings)
    return AccessTokenResponse(access_token=token, expires_in=expires_in)


@router.post(
    "/register-tenant-admin",
    response_model=AccessTokenResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"description": "Tenant or user already exists"}},
)
async def register_tenant_admin_endpoint(
    payload: RegisterTenantAdminRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AccessTokenResponse:
    """Register a tenant and its first merchant administrator."""

    try:
        user = await register_tenant_admin(session, payload)
    except RegistrationConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration already exists",
        ) from None
    return token_response(user.id, settings)


@router.post("/login", response_model=AccessTokenResponse)
async def login(
    payload: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AccessTokenResponse:
    """Authenticate with a password and return an expiring access token."""

    try:
        user = await authenticate(session, payload.email, payload.password)
    except AuthenticationFailedError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    return token_response(user.id, settings)


@router.get("/me", response_model=CurrentUserResponse)
async def me(
    identity: Annotated[CurrentIdentity, Depends(require_current_identity)],
) -> CurrentUserResponse:
    """Return the server-verified current user and tenant membership."""

    return CurrentUserResponse(**identity.__dict__)
