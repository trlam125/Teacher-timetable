"""Prevent framing on every HTTP response, including unhandled server errors."""
from __future__ import annotations

from fastapi import FastAPI
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class FrameProtectionMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def protected_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (name, value) for name, value in message.get("headers", [])
                    if name.lower() != b"x-frame-options"
                ]
                # Browsers enforce each CSP header, so keep any existing policy.
                headers.extend([
                    (b"content-security-policy", b"frame-ancestors 'none'"),
                    (b"x-frame-options", b"DENY"),
                ])
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, protected_send)


class FrameProtectedFastAPI(FastAPI):
    def build_middleware_stack(self) -> ASGIApp:
        # User middleware runs inside Starlette's server-error handler. Wrap the
        # completed stack so its 500 responses receive the same protection.
        return FrameProtectionMiddleware(super().build_middleware_stack())
