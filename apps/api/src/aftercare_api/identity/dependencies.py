"""FastAPI dependencies for protected endpoints."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from aftercare_api.config import Settings, get_settings
from aftercare_api.db.session import get_session
from aftercare_api.identity.security import InvalidCredentialsError, decode_access_token
from aftercare_api.identity.service import (
    AuthenticationFailedError,
    CurrentIdentity,
    get_current_identity,
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def require_current_identity(
    request: Request,
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CurrentIdentity:
    """Resolve a bearer token into an active database-backed identity."""

    try:
        user_id = decode_access_token(token, settings)
        identity = await get_current_identity(session, user_id)
        set_audit_identity(request, session, identity)
        return identity
    except (InvalidCredentialsError, AuthenticationFailedError):
        raise credentials_exception from None


def set_audit_identity(request: Request, session: AsyncSession, identity: CurrentIdentity) -> None:
    """Expose only a verified identity and database binding to the audit recorder."""

    request.state.audit_identity = identity
    request.state.audit_bind = session.bind


def require_roles(*roles: str):
    """Require an allowed database-backed role without widening resource ownership."""

    async def check_role(
        identity: Annotated[CurrentIdentity, Depends(require_current_identity)],
    ) -> CurrentIdentity:
        if identity.role not in roles:
            raise HTTPException(status_code=403, detail="Role not permitted")
        return identity

    return check_role
