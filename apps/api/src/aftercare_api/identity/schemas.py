"""Request and response schemas for identity endpoints."""

from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class RegisterTenantAdminRequest(BaseModel):
    """Payload for creating a merchant tenant and its first administrator."""

    tenant_name: str = Field(min_length=2, max_length=120)
    tenant_slug: str = Field(min_length=3, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Normalize email input before uniqueness checks."""

        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Email must be valid")
        return normalized


class LoginRequest(BaseModel):
    """Payload for password login."""

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Normalize email input before lookup."""

        return value.strip().lower()


class AccessTokenResponse(BaseModel):
    """A short-lived bearer access token."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class CurrentUserResponse(BaseModel):
    """Current authenticated user and server-verified tenant membership."""

    user_id: UUID
    email: str
    tenant_id: UUID
    tenant_name: str
    role: str
