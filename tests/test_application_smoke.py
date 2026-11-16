"""Exercise real routes with dummy configuration and blocked external I/O."""
from __future__ import annotations

import io
import unittest
from unittest.mock import Mock, patch

import httpx


def setUpModule():
    global create_app, engine, system, environment
    environment = patch.dict("os.environ", {
        "DATABASE_URL": "postgresql://test:test@127.0.0.1:1/test",
        "SECRET_KEY": "test-only-secret-not-for-production-0123456789",
        "APP_ENV": "production", "APP_BASE_URL": "https://test.invalid",
    })
    environment.start()
    with patch("dotenv.load_dotenv", return_value=False):
        from app.main import create_app
        from app.database import engine
        from app.routers import system


def tearDownModule():
    engine.dispose()
    environment.stop()


class ApplicationSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_guard = patch.object(engine, "connect", side_effect=AssertionError("Unexpected database access"))
        self.network_guard = patch("socket.create_connection", side_effect=AssertionError("Unexpected external connection"))
        self.db_guard.start()
        self.network_guard.start()
        self.addCleanup(self.db_guard.stop)
        self.addCleanup(self.network_guard.stop)
        # ASGITransport does not run lifespan/bootstrap; no production DB is started.
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app()), base_url="https://test.invalid"
        )
        self.addAsyncCleanup(self.client.aclose)

    async def test_health_and_clock(self):
        health = await self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"status": "ok"})
        clock = await self.client.get("/api/server-time")
        self.assertEqual(clock.status_code, 200)
        self.assertEqual(clock.json()["timezone"], "Asia/Ho_Chi_Minh")

    async def test_login_registration_and_password_reset_templates_render(self):
        for path in ("/login", "/register", "/forgot-password"):
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn("text/html", response.headers["content-type"])
                self.assertIn("captcha", response.text.lower())

    async def test_openapi_builds_with_upgraded_dependencies(self):
        response = await self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("/api/schedule-audit", response.json()["paths"])
        self.assertIn("/api/projects/{pid}/chatbot", response.json()["paths"])

    async def test_unauthenticated_upload_still_requires_login(self):
        response = await self.client.post(
            "/api/schedule-audit", files={"file": ("test.csv", b"a,b\n1,2\n", "text/csv")}
        )
        self.assertEqual(response.status_code, 401)

    async def test_missing_page_renders_html_error_template(self):
        response = await self.client.get("/does-not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertIn("text/html", response.headers["content-type"])

    async def test_weather_cache_prevents_duplicate_upstream_calls(self):
        from app.services.traffic import TTLCache, TokenBuckets

        with (patch.object(system, "_weather_cache", TTLCache(600)),
              patch.object(system, "_weather_requests", TokenBuckets(2, 4, capacity=1)),
              patch("urllib.request.urlopen", return_value=io.BytesIO(b'{"current":{"temperature_2m":25}}')) as upstream):
            for _ in range(2):
                response = await self.client.get("/api/weather?latitude=10&longitude=106")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["current"]["temperature_2m"], 25)
            self.assertEqual(upstream.call_count, 1)

    async def test_upstream_throttle_preserves_retry_after(self):
        from app.services.traffic import TTLCache

        with (patch.object(system, "_weather_cache", TTLCache(600)),
              patch.object(system, "_weather_requests", Mock(allow=Mock(return_value=False))),
              patch("urllib.request.urlopen", side_effect=AssertionError("Throttle must run before network"))):
            response = await self.client.get("/api/weather?latitude=10&longitude=106")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], "2")


if __name__ == "__main__":
    unittest.main()
