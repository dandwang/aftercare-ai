"""FastAPI dependencies for protected endpoints."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
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
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CurrentIdentity:
    """Resolve a bearer token into an active database-backed identity."""

    try:
        user_id = decode_access_token(token, settings)
        return await get_current_identity(session, user_id)
    except (InvalidCredentialsError, AuthenticationFailedError):
        raise credentials_exception from None
