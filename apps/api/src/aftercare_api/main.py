from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aftercare_api.config import get_settings
from aftercare_api.health import router as health_router
from aftercare_api.identity.router import router as identity_router

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(health_router)
app.include_router(identity_router)
