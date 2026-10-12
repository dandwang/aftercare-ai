"""Create fictional roles only in the disposable demonstration database."""

import asyncio
from getpass import getpass

from sqlalchemy import select

from aftercare_api.config import get_settings
from aftercare_api.db.session import SessionLocal, engine
from aftercare_api.identity.models import Tenant, TenantMembership, User
from aftercare_api.identity.security import hash_password

ACCOUNTS = {
    "merchant_admin": "admin@demo.example.test",
    "support_agent": "support@demo.example.test",
    "customer": "customer@demo.example.test",
}


async def seed(password: str) -> None:
    """Create the complete demo set atomically; never update existing identities."""

    if get_settings().database_url.rsplit("/", 1)[-1] != "aftercare_m2d":
        raise RuntimeError("Demo accounts require the disposable aftercare_m2d database")
    if len(password) < 12:
        raise ValueError("Use a demo password with at least 12 characters")
    async with SessionLocal() as session, session.begin():
        if await session.scalar(select(Tenant.id).where(Tenant.slug == "m2-demo")):
            raise RuntimeError("Demo tenant already exists; existing accounts were not changed")
        if await session.scalar(select(User.id).where(User.email.in_(ACCOUNTS.values()))):
            raise RuntimeError("Demo email already exists; existing accounts were not changed")
        tenant = Tenant(name="M2 Demo Store", slug="m2-demo")
        session.add(tenant)
        await session.flush()
        for role, email in ACCOUNTS.items():
            user = User(email=email, password_hash=hash_password(password))
            session.add(user)
            await session.flush()
            session.add(TenantMembership(tenant_id=tenant.id, user_id=user.id, role=role))
    print("Created M2 Demo Store accounts:")
    for role, email in ACCOUNTS.items():
        print(f"{role}: {email}")


async def main() -> None:
    try:
        password = getpass("Demo password (at least 12 characters): ")
        if password != getpass("Repeat demo password: "):
            raise ValueError("Passwords do not match")
        await seed(password)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
