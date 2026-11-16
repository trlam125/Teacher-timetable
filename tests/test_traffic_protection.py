"""Offline regression checks; dummy ASGI apps only, no application database."""
from __future__ import annotations

import asyncio
import io
import unittest
from unittest.mock import patch

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.services.request_protection import RequestProtectionMiddleware
from app.services.traffic import TTLCache, TokenBuckets


def http_scope(path="/upload", headers=(), client="192.0.2.1", method="POST"):
    return {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
            "query_string": b"", "headers": list(headers), "client": (client, 1234),
            "server": ("test.invalid", 80)}


async def invoke(app, scope=None, chunks=(b"",)):
    messages = [{"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1}
                for i, chunk in enumerate(chunks)]
    sent = []

    async def receive():
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await app(scope or http_scope(), receive, send)
    return sent


def status(sent):
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


class BucketTests(unittest.TestCase):
    def test_many_new_identities_cannot_evict_an_active_limit(self):
        buckets = TokenBuckets(rate=1, burst=2, capacity=2)
        self.assertTrue(buckets.allow("victim", now=0))
        self.assertTrue(buckets.allow("victim", now=0))
        self.assertTrue(buckets.allow("other", now=0))
        self.assertFalse(buckets.allow("new", now=0))
        self.assertFalse(buckets.allow("victim", now=0))
        self.assertTrue(buckets.allow("new", now=3))
        self.assertLessEqual(len(buckets._buckets), 2)

    def test_cache_expires_and_evicts_the_least_recent_entry(self):
        cache = TTLCache(ttl=10, capacity=2)
        with patch("app.services.traffic.time.monotonic", return_value=0):
            cache.put("a", 1)
            cache.put("b", 2)
            self.assertEqual(cache.get("a"), 1)
            cache.put("c", 3)
            self.assertIsNone(cache.get("b"))
        with patch("app.services.traffic.time.monotonic", return_value=11):
            self.assertIsNone(cache.get("a"))
            cache.put("d", 4)
            self.assertEqual(list(cache._items), ["d"])


class RequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_content_length_rejected_before_app_or_body_read(self):
        async def forbidden(*args):
            self.fail("Oversized request reached application")
        app = RequestProtectionMiddleware(forbidden, max_body_bytes=8)
        sent = await invoke(app, http_scope(headers=[(b"content-length", b"9")]))
        self.assertEqual(status(sent), 413)

    async def test_chunked_body_stops_before_overflow_chunk_reaches_parser(self):
        accepted = []

        async def reader(scope, receive, send):
            while True:
                message = await receive()
                accepted.append(message["body"])
                if not message.get("more_body"):
                    break
            await JSONResponse({"ok": True})(scope, receive, send)

        app = RequestProtectionMiddleware(reader, max_body_bytes=8)
        sent = await invoke(app, chunks=(b"12345", b"67890"))
        self.assertEqual(status(sent), 413)
        self.assertEqual(accepted, [b"12345"])
        self.assertEqual(app._body_active, 0)

    async def test_multipart_overflow_closes_partial_files_and_returns_413(self):
        partial_files = []

        def spool(*args, **kwargs):
            file = io.BytesIO()
            partial_files.append(file)
            return file

        async def upload(request):
            async with request.form():
                self.fail("Oversized multipart reached endpoint logic")

        inner = Starlette(routes=[Route("/upload", upload, methods=["POST"])])
        app = RequestProtectionMiddleware(inner, max_body_bytes=180)
        prefix = b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="x.txt"\r\n\r\n'
        scope = http_scope(headers=[(b"content-type", b"multipart/form-data; boundary=boundary")])
        with patch("starlette.formparsers.SpooledTemporaryFile", side_effect=spool):
            sent = await invoke(app, scope, (prefix, b"a" * 200, b"\r\n--boundary--\r\n"))
        self.assertEqual(status(sent), 413)
        self.assertTrue(partial_files)
        self.assertTrue(all(f.closed for f in partial_files))
        self.assertEqual(sum(m["type"] == "http.response.start" for m in sent), 1)

    async def test_valid_multipart_still_reaches_endpoint(self):
        async def upload(request):
            async with request.form() as form:
                content = await form["file"].read()
                return JSONResponse({"size": len(content)})
        inner = Starlette(routes=[Route("/upload", upload, methods=["POST"])])
        app = RequestProtectionMiddleware(inner, max_body_bytes=512)
        content = (b'--b\r\nContent-Disposition: form-data; name="file"; filename="x"\r\n\r\n'
                   b'hello\r\n--b--\r\n')
        scope = http_scope(headers=[(b"content-type", b"multipart/form-data; boundary=b")])
        sent = await invoke(app, scope, (content,))
        self.assertEqual(status(sent), 200)
        self.assertEqual(sent[-1]["body"], b'{"size":5}')

    async def test_forwarded_header_cannot_change_application_rate_identity(self):
        async def ok(scope, receive, send):
            await JSONResponse({})(scope, receive, send)
        app = RequestProtectionMiddleware(ok, burst=1)
        first = await invoke(app, http_scope(headers=[(b"x-forwarded-for", b"198.51.100.1")]))
        second = await invoke(app, http_scope(headers=[(b"x-forwarded-for", b"198.51.100.2")]))
        self.assertEqual(status(first), 200)
        self.assertEqual(status(second), 429)

    async def test_slow_body_times_out_and_releases_admission(self):
        async def reader(scope, receive, send):
            await receive()
        async def slow():
            await asyncio.Event().wait()
        sent = []
        async def send(message):
            sent.append(message)
        app = RequestProtectionMiddleware(reader, body_timeout=0.01)
        await app(http_scope(), slow, send)
        self.assertEqual(status(sent), 408)
        self.assertEqual((app._http_active, app._body_active), (0, 0))

    async def test_body_concurrency_rejects_without_waiting_and_recovers(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def reader(scope, receive, send):
            entered.set()
            await release.wait()
            await JSONResponse({})(scope, receive, send)
        app = RequestProtectionMiddleware(reader, max_body_requests=1)
        first = asyncio.create_task(invoke(app))
        await entered.wait()
        try:
            self.assertEqual(status(await invoke(app)), 503)
        finally:
            release.set()
            await first
        self.assertEqual(status(await invoke(app)), 200)

    async def test_websocket_oversize_is_rejected_before_endpoint_receives_frame(self):
        async def socket(scope, receive, send):
            await receive()
            await send({"type": "websocket.accept"})
            self.assertEqual((await receive())["type"], "websocket.disconnect")
        app = RequestProtectionMiddleware(socket, ws_message_bytes=4)
        scope = http_scope()
        scope["type"] = "websocket"
        frames = [{"type": "websocket.connect"}, {"type": "websocket.receive", "text": "hello"}]
        sent = []
        async def receive():
            return frames.pop(0)
        async def send(message):
            sent.append(message)
        await app(scope, receive, send)
        self.assertEqual(sent[-1], {"type": "websocket.close", "code": 1009})
        self.assertEqual(app._ws_active, 0)
        self.assertEqual(app._ws_ips, {})

    async def test_small_login_is_not_blocked_by_a_busy_upload_slot(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def endpoint(scope, receive, send):
            if scope["path"] == "/upload":
                entered.set()
                await release.wait()
            await JSONResponse({})(scope, receive, send)
        app = RequestProtectionMiddleware(endpoint, max_body_requests=1)
        upload = asyncio.create_task(invoke(app))
        await entered.wait()
        try:
            login = http_scope("/login", headers=[(b"content-length", b"20")])
            self.assertEqual(status(await invoke(app, login)), 200)
        finally:
            release.set()
            await upload


if __name__ == "__main__":
    unittest.main()
