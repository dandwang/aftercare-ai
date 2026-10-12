"""Record one allowlisted API action without inspecting bodies or SSE chunks."""

import logging
from uuid import UUID

import anyio
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from aftercare_api.audit.models import AuditEvent

logger = logging.getLogger(__name__)
CONVERSATIONS = "/api/v1/conversations"
ACTIONS = {
    ("POST", "/api/v1/auth/register-tenant-admin"): ("auth.register", "tenant"),
    ("POST", "/api/v1/auth/login"): ("auth.login", "identity"),
    ("GET", "/api/v1/auth/me"): ("auth.me", "identity"),
    ("POST", CONVERSATIONS): ("conversation.create", "conversation"),
    ("GET", CONVERSATIONS): ("conversation.list", "conversation"),
    ("GET", CONVERSATIONS + "/{conversation_id}"): ("conversation.read", "conversation"),
    ("POST", CONVERSATIONS + "/{conversation_id}/messages"): ("message.send", "conversation"),
    ("POST", CONVERSATIONS + "/{conversation_id}/messages/stream"): (
        "message.stream",
        "conversation",
    ),
    ("POST", CONVERSATIONS + "/{conversation_id}/messages/{message_id}/stop"): (
        "message.stop",
        "message",
    ),
    ("POST", CONVERSATIONS + "/{conversation_id}/messages/{message_id}/regenerate/stream"): (
        "message.regenerate",
        "message",
    ),
    ("POST", CONVERSATIONS + "/{conversation_id}/messages/{message_id}/feedback"): (
        "feedback.save",
        "message",
    ),
    ("GET", "/api/v1/audit-events"): ("audit.list", "audit"),
}


class AuditMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status_code = 500

        async def capture_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture_status)
        finally:
            await self.record(scope, status_code)

    async def record(self, scope: Scope, status_code: int) -> None:
        state = scope.get("state", {})
        identity = state.get("audit_identity")
        route = scope.get("route")
        action = ACTIONS.get((scope["method"], getattr(route, "path", None)))
        if identity is None or action is None:
            return
        action_name, resource_type = action
        params = scope.get("path_params", {})
        resource_id = (
            state.get("audit_resource_id")
            or params.get("message_id")
            or params.get("conversation_id")
        )
        if resource_type == "tenant":
            resource_id = identity.tenant_id
        elif resource_type == "identity":
            resource_id = identity.user_id
        try:
            resource_id = UUID(str(resource_id)) if resource_id else None
        except ValueError:
            resource_id = None
        result = "success"
        if status_code in (401, 403, 404):
            result = "denied"
        elif status_code >= 400:
            result = "failure"
        elif action_name in ("message.stream", "message.regenerate"):
            result = "accepted"
        # A separate session cannot commit or roll back the business transaction.
        with anyio.move_on_after(3, shield=True) as recording_scope:
            try:
                factory = async_sessionmaker(state["audit_bind"], expire_on_commit=False)
                async with factory() as session, session.begin():
                    session.add(
                        AuditEvent(
                            tenant_id=identity.tenant_id,
                            actor_user_id=identity.user_id,
                            actor_role=identity.role,
                            action=action_name,
                            resource_type=resource_type,
                            resource_id=resource_id,
                            status_code=status_code,
                            result=result,
                        )
                    )
            except Exception as exc:
                logger.error("Audit recording failed: %s", type(exc).__name__)
        if recording_scope.cancel_called:
            logger.error("Audit recording timed out")
