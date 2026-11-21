"""Endurecimiento de la API local: solo orígenes y hosts esperados (CSRF / DNS-rebinding)."""
import os

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

ALLOWED_ORIGINS = {
    o.strip() for o in os.environ.get("AUDIT_ALLOWED_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",") if o.strip()
}
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("AUDIT_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]


def origin_allowed(origin: str | None) -> bool:
    """Sin cabecera Origin (curl, tests, mismo origen sin CORS) se permite; si la hay, debe estar en la lista."""
    return origin is None or origin in ALLOWED_ORIGINS


class OriginGuardMiddleware:
    """Rechaza peticiones que modifican estado cuando llegan con un Origin ajeno."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http" and scope["method"] not in ("GET", "HEAD", "OPTIONS"):
            origin = dict(scope["headers"]).get(b"origin")
            if not origin_allowed(origin.decode() if origin else None):
                await PlainTextResponse("Origen no permitido", status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)
