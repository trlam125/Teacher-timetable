"""ASGI limits run before routing, body parsing and database dependencies."""
from __future__ import annotations

import asyncio
import time

from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse

from app.services.traffic import TokenBuckets


class _BodyRejected(MultiPartException):
    # Multipart parsers catch this base class and close partial temporary files.
    def __init__(self, status: int):
        super().__init__("Request body rejected")
        self.status = status


class RequestProtectionMiddleware:
    def __init__(self, app, *, max_body_bytes=32 * 1024 * 1024,
                 body_timeout=30.0, requests_per_minute=600, burst=120,
                 max_http=64, max_body_requests=4, max_websockets=128,
                 ws_per_ip=16, ws_message_bytes=32768, ws_events_per_minute=120,
                 ws_event_burst=30):
        self.app = app
        self.max_body_bytes, self.body_timeout = max_body_bytes, body_timeout
        self.max_http, self.max_websockets = max_http, max_websockets
        self.max_body_requests = max_body_requests
        self.ws_per_ip, self.ws_message_bytes = ws_per_ip, ws_message_bytes
        self._http_active = self._ws_active = 0
        self._body_active = 0
        self._ws_ips: dict[str, int] = {}
        self._http = TokenBuckets(requests_per_minute / 60, burst)
        self._total = TokenBuckets(120, 240, capacity=1)
        self._auth = TokenBuckets(1, 20)
        self._public = TokenBuckets(0.5, 10)
        self._ws_events = TokenBuckets(ws_events_per_minute / 60, ws_event_burst)

    async def __call__(self, scope, receive, send):
        kind = scope["type"]
        if kind not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        # Uvicorn resolves forwarded addresses only from explicitly trusted proxies.
        # Never trust a client-supplied X-Forwarded-For/CF-Connecting-IP here.
        client = scope.get("client")
        identity = str(client[0])[:128] if client else "unknown"
        if kind == "websocket":
            if sum(len(k) + len(v) for k, v in scope.get("headers", [])) > 16384:
                return await send({"type": "websocket.close", "code": 1008})
            return await self._websocket(scope, receive, send, identity)

        async def reject(status):
            text = {400: "Invalid request framing", 408: "Request body timed out",
                    413: "Request body too large", 429: "Too many requests",
                    431: "Request headers too large", 503: "Server busy"}[status]
            headers = {"Cache-Control": "no-store"}
            if status in {429, 503}:
                headers["Retry-After"] = "5"
            if scope.get("http_version") == "1.1":
                headers["Connection"] = "close"
            await JSONResponse({"ok": False, "message": text, "detail": text}, status, headers)(scope, receive, send)

        headers = scope.get("headers", [])
        if sum(len(k) + len(v) for k, v in headers) > 16384:
            return await reject(431)
        lengths = [v for k, v in headers if k.lower() == b"content-length"]
        if len(lengths) > 1 or (lengths and (not lengths[0].isdigit() or len(lengths[0]) > 12)):
            return await reject(400)
        if lengths and any(k.lower() == b"transfer-encoding" for k, _ in headers):
            return await reject(400)
        if lengths and int(lengths[0]) > self.max_body_bytes:
            return await reject(413)
        # Bound multi-range work even if a future file-serving regression appears.
        ranges = [v for k, v in headers if k.lower() == b"range"]
        if len(ranges) > 1 or any(len(v) > 2048 or v.count(b",") > 15 for v in ranges):
            return await reject(400)
        if not self._total.allow("all") or not self._http.allow(identity):
            return await reject(429)
        path = scope.get("path", "")
        if (path in {"/login", "/register", "/forgot-password"}
                or path.startswith(("/auth/", "/register/", "/reset-password/", "/account/email-change"))):
            if not self._auth.allow(identity):
                return await reject(429)
        if path in {"/api/weather", "/api/location-name"} and not self._public.allow(identity):
            return await reject(429)
        if self._http_active >= self.max_http:
            return await reject(503)
        has_body = scope.get("method", "GET") in {"POST", "PUT", "PATCH", "DELETE"}
        has_body = has_body or bool(lengths and int(lengths[0])) or any(
            k.lower() == b"transfer-encoding" for k, _ in headers
        )
        # Keep large/unknown uploads separate so slow file/AI requests cannot
        # occupy every admission slot used by small login/edit forms.
        body_slot = has_body and (not lengths or int(lengths[0]) > 64 * 1024)
        if body_slot and self._body_active >= self.max_body_requests:
            return await reject(503)
        self._http_active += 1
        if body_slot:
            self._body_active += 1
        received = 0
        body_finished = False
        deadline = time.monotonic() + self.body_timeout
        rejected = None
        rejection_sent = False
        response_started = False

        async def limited_receive():
            nonlocal received, rejected, body_finished, body_slot
            # Streaming responses may listen for disconnect after sending headers;
            # that receive is no longer part of parsing the request body.
            if body_finished or response_started:
                return await receive()
            try:
                message = await asyncio.wait_for(receive(), max(0, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                rejected = 408
                raise _BodyRejected(408)
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    rejected = 413
                    raise _BodyRejected(413)
                if received > 64 * 1024 and not body_slot:
                    if self._body_active >= self.max_body_requests:
                        rejected = 503
                        raise _BodyRejected(503)
                    self._body_active += 1
                    body_slot = True
                body_finished = not message.get("more_body", False)
                if body_finished and received <= 64 * 1024 and body_slot:
                    self._body_active -= 1
                    body_slot = False
            return message

        async def limited_send(message):
            nonlocal rejection_sent, response_started
            if rejected is None:
                if message["type"] == "http.response.start":
                    response_started = True
                await send(message)
            elif not rejection_sent:
                rejection_sent = True
                await reject(rejected)

        try:
            await self.app(scope, limited_receive, limited_send)
        except _BodyRejected:
            pass
        finally:
            self._http_active -= 1
            if body_slot:
                self._body_active -= 1
        if rejected is not None and not rejection_sent:
            await reject(rejected)

    async def _websocket(self, scope, receive, send, identity):
        if (self._ws_active >= self.max_websockets or self._ws_ips.get(identity, 0) >= self.ws_per_ip
                or not self._http.allow(identity) or not self._total.allow("all")):
            return await send({"type": "websocket.close", "code": 1013})
        self._ws_active += 1
        self._ws_ips[identity] = self._ws_ips.get(identity, 0) + 1

        async def limited_receive():
            message = await receive()
            if message["type"] == "websocket.receive":
                data = message.get("bytes")
                size = len(data) if data is not None else len((message.get("text") or "").encode("utf-8"))
                if size > self.ws_message_bytes or not self._ws_events.allow(identity):
                    await send({"type": "websocket.close", "code": 1009 if size > self.ws_message_bytes else 1008})
                    return {"type": "websocket.disconnect", "code": 1008}
            return message

        try:
            await self.app(scope, limited_receive, send)
        finally:
            self._ws_active -= 1
            self._ws_ips[identity] -= 1
            if not self._ws_ips[identity]:
                del self._ws_ips[identity]
