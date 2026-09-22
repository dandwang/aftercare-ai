"""Password hashing and JWT helpers."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from aftercare_api.config import Settings

password_hasher = PasswordHasher()


class InvalidCredentialsError(Exception):
    """Raised when credentials or a token cannot establish an identity."""


def hash_password(password: str) -> str:
    """Hash a password with Argon2 without persisting plaintext."""

    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against an Argon2 hash."""

    try:
        return password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def create_access_token(user_id: UUID, settings: Settings) -> tuple[str, int]:
    """Create a signed, expiring access token with only an identity subject."""

    issued_at = datetime.now(UTC)
    lifetime = timedelta(minutes=settings.access_token_expire_minutes)
    expires_at = issued_at + lifetime
    token = jwt.encode(
        {"sub": str(user_id), "iat": issued_at, "exp": expires_at},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str, settings: Settings) -> UUID:
    """Validate a signed access token and return its user subject."""

    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return UUID(str(payload["sub"]))
    except (KeyError, ValueError, jwt.InvalidTokenError) as error:
        raise InvalidCredentialsError from error
