"""Device admission regressions using disposable SQLite and stubbed email only."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from http.cookies import SimpleCookie
import os
import secrets
import time
import unittest
from unittest.mock import patch

os.environ["DATABASE_URL"] = "postgresql://test:test@127.0.0.1:1/unused"
os.environ["SECRET_KEY"] = "offline-device-session-regression-only-never-deploy"
os.environ["APP_ENV"] = "production"
os.environ["APP_BASE_URL"] = "https://testserver"

from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.errors import register_exception_handlers
from app.models import AccountDevice, Base, DeviceLoginChallenge, User
from app.routers.auth_routes import devices as retired_routes, login, logout
from app.services.authentication import csrf, devices, sessions
from app.services.authentication.credentials import pwd, signer
from app.services.authentication.mail import send_device_login_alert_email
from app.services.authentication.permissions import is_super_admin, user_can_access_school
from app.services.authentication.verification import normalize_otp


def request(cookies=None):
    headers = [(b"host", b"testserver"), (b"user-agent", b"Chrome/140 Windows")]
    if cookies:
        headers.append((b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()))
    return Request({"type": "http", "method": "POST", "scheme": "https", "path": "/login",
                    "query_string": b"", "server": ("testserver", 443),
                    "client": ("127.0.0.1", 1234), "headers": headers})


def apply_cookies(cookies, response):
    for header in response.headers.getlist("set-cookie"):
        parsed = SimpleCookie()
        parsed.load(header)
        for name, value in parsed.items():
            if value["max-age"] == "0":
                cookies.pop(name, None)
            else:
                cookies[name] = value.value


class DeviceSessionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool,
                                    connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.factory()
        self.user = User(name="Test Admin", email="admin@example.invalid",
                         password_hash=pwd.hash("disposable-password"), role="super_admin", is_superadmin=True)
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def admit(self, cookies=None, user=None):
        cookies = cookies if cookies is not None else {}
        response = devices.begin_login(request(cookies), self.db, user or self.user)
        apply_cookies(cookies, response)
        return cookies, response

    def live(self):
        return self.db.scalars(select(AccountDevice).where(AccountDevice.session_hash.is_not(None),
            AccountDevice.session_expires_at > int(time.time()))).all()

    def test_super_admin_enters_directly_without_device_otp(self):
        cookies, response = self.admit()
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/projects")
        self.assertTrue(is_super_admin(sessions.session_user(cookies, self.db)))
        self.assertTrue(user_can_access_school(self.user, None, self.db))
        self.assertEqual(self.db.scalars(select(DeviceLoginChallenge)).all(), [])
        self.assertNotIn(devices.PENDING_COOKIE, cookies)

    def test_teacher_login_also_needs_no_device_code(self):
        self.user.role = "teacher"
        self.db.commit()
        cookies, response = self.admit()
        self.assertEqual(response.headers["location"], "/teacher")
        self.assertIsNotNone(sessions.session_user(cookies, self.db))

    def test_google_login_uses_same_direct_admission_and_share_redirect(self):
        from app.routers.social_auth import finish
        from app.services.authentication import navigation
        cookies = {navigation.SHARE_RETURN_COOKIE: navigation._signer.dumps({"path": "/share/test-link"})}
        response = finish(self.db, self.user, request(cookies))
        apply_cookies(cookies, response)
        self.assertEqual(response.headers["location"], "/share/test-link")
        self.assertIsNotNone(sessions.session_user(cookies, self.db))
        self.assertNotIn(devices.PENDING_COOKIE, cookies)

    def test_third_login_revokes_least_recent_session_but_remembers_all_browsers(self):
        first, _ = self.admit()
        second, _ = self.admit()
        old_device = self.db.get(AccountDevice, signer.loads(first["session"])["did"])
        old_device.last_used_at = int(time.time()) - 120
        self.db.commit()
        third, _ = self.admit()
        self.assertIsNone(sessions.session_user(first, self.db))
        self.assertIsNotNone(sessions.session_user(second, self.db))
        self.assertIsNotNone(sessions.session_user(third, self.db))
        self.assertEqual(len(self.live()), 2)
        self.assertEqual(len(self.db.scalars(select(AccountDevice)).all()), 3)

    def test_many_browsers_can_log_in_without_an_account_device_quota(self):
        for _ in range(7):
            cookies, response = self.admit()
            self.assertEqual(response.status_code, 303)
            self.assertIsNotNone(sessions.session_user(cookies, self.db))
            self.assertLessEqual(len(self.live()), 2)
        self.assertEqual(len(self.db.scalars(select(AccountDevice)).all()), 7)

    def test_logged_out_and_expired_devices_do_not_evict_a_live_device(self):
        logged_out, _ = self.admit()
        row = self.live()[0]
        row.session_hash = None
        row.session_expires_at = 0
        self.db.commit()
        expired, _ = self.admit()
        self.live()[0].session_expires_at = int(time.time()) - 1
        self.db.commit()
        current, _ = self.admit()
        another, _ = self.admit()
        self.assertIsNone(sessions.session_user(logged_out, self.db))
        self.assertIsNone(sessions.session_user(expired, self.db))
        self.assertIsNotNone(sessions.session_user(current, self.db))
        self.assertIsNotNone(sessions.session_user(another, self.db))

    def test_known_browser_rotates_its_session_without_evicting_other_browser(self):
        first, _ = self.admit()
        old_cookie = dict(first)
        other, _ = self.admit()
        first, response = self.admit(first)
        self.assertIsNone(response.background)
        self.assertIsNone(sessions.session_user(old_cookie, self.db))
        self.assertIsNotNone(sessions.session_user(first, self.db))
        self.assertIsNotNone(sessions.session_user(other, self.db))
        self.assertEqual(len(self.db.scalars(select(AccountDevice)).all()), 2)

    def test_new_browser_alert_runs_after_login_and_mail_failure_does_not_block(self):
        cookies, response = self.admit()
        for outcome in (False, RuntimeError("mail unavailable")):
            kwargs = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
            with patch.object(devices, "send_device_login_alert_email", **kwargs) as send:
                asyncio.run(response.background())
                send.assert_called_once()
            self.assertIsNotNone(sessions.session_user(cookies, self.db))

    def test_browser_cookie_alone_or_copied_session_does_not_authenticate(self):
        cookies, _ = self.admit()
        self.assertIsNone(sessions.session_user({sessions.DEVICE_COOKIE: cookies[sessions.DEVICE_COOKIE]}, self.db))
        copied = dict(cookies, trusted_browser=secrets.token_urlsafe(32))
        self.assertIsNone(sessions.session_user(copied, self.db))

    def test_password_change_invalidates_old_sessions(self):
        first, _ = self.admit()
        second, _ = self.admit()
        sessions.invalidate_credential_state(self.user)
        self.db.commit()
        self.assertIsNone(sessions.session_user(first, self.db))
        self.assertIsNone(sessions.session_user(second, self.db))

    def test_existing_super_admin_without_legacy_flag_can_still_log_in(self):
        self.user.is_superadmin = False
        self.db.commit()
        cookies, _ = self.admit()
        self.assertEqual(sessions.session_user(cookies, self.db).role, "super_admin")

    def test_unknown_role_stays_forbidden(self):
        self.user.role = "disabled"
        self.db.commit()
        with self.assertRaises(HTTPException) as raised:
            self.admit()
        self.assertEqual(raised.exception.status_code, 403)

    def app(self):
        app = FastAPI(dependencies=[Depends(csrf.verify_request_csrf)])
        register_exception_handlers(app)
        app.include_router(login.router)
        app.include_router(logout.router)
        app.include_router(retired_routes.router)
        def test_db():
            with self.factory() as db:
                yield db
        app.dependency_overrides[sessions.db_session] = test_db
        @app.get("/projects")
        def projects(user=Depends(sessions.current_user)):
            return {"role": user.role}
        @app.get("/forbidden")
        def forbidden():
            raise HTTPException(403)
        return app

    def test_real_login_form_with_csrf_succeeds_for_super_admin_and_logout_frees_slot(self):
        with TestClient(self.app(), base_url="https://testserver") as client:
            page = client.get("/login")
            token = page.context["csrf_token"]
            with patch.object(login, "rate_limit_blocked", return_value=False), \
                 patch.object(login, "clear_rate_limit_bucket"), \
                 patch.object(devices, "send_device_login_alert_email", return_value=True) as send:
                result = client.post("/login", data={"csrf_token": token, "email": self.user.email,
                                                      "password": "disposable-password"})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["role"], "super_admin")
            send.assert_called_once()
            result = client.post("/logout", data={"csrf_token": token}, follow_redirects=False)
            self.assertEqual(result.status_code, 303)
            self.db.expire_all()
            self.assertEqual(len(self.live()), 0)

    def test_expired_form_error_does_not_claim_super_admin_has_lost_permissions(self):
        with TestClient(self.app(), base_url="https://testserver") as client:
            result = client.post("/login", data={"email": self.user.email, "password": "unused"})
            self.assertEqual(result.status_code, 403)
            self.assertIn("Vui lòng mở lại biểu mẫu", result.text)
            self.assertNotIn("Bạn chưa có quyền truy cập", result.text)
            result = client.post("/login", headers={"X-Requested-With": "XMLHttpRequest"}, data={})
            self.assertEqual(result.json()["code"], "expired_form")
            self.assertEqual(client.get("/forbidden").status_code, 403)
            self.assertIn("Bạn chưa có quyền truy cập", client.get("/forbidden").text)

    def test_retired_otp_pages_return_to_login_and_never_create_a_session(self):
        with TestClient(self.app(), base_url="https://testserver") as client:
            result = client.get("/auth/device", follow_redirects=False)
            self.assertEqual(result.headers["location"], "/login")
            page = client.get("/login")
            result = client.post("/auth/device/verify", data={"csrf_token": page.context["csrf_token"], "otp": "123456"},
                                 follow_redirects=False)
            self.assertEqual(result.headers["location"], "/login")
            self.assertNotIn("session", client.cookies)

    def test_csrf_origin_and_binding_are_still_enforced(self):
        cookies = {csrf.CSRF_COOKIE: secrets.token_urlsafe(32)}
        token = csrf.form_token(request(cookies))[1]
        csrf.require_form_token(request(cookies), token)
        with self.assertRaises(csrf.FormSecurityError):
            csrf.require_form_token(request({csrf.CSRF_COOKIE: secrets.token_urlsafe(32)}), token)
        req = request(cookies)
        req.scope["headers"].append((b"origin", b"https://attacker.invalid"))
        with self.assertRaises(csrf.FormSecurityError) as raised:
            csrf.require_form_token(req, token)
        self.assertEqual(raised.exception.code, "invalid_origin")

    def test_pasted_code_normalization_preserves_leading_zeroes_and_rejects_garbage(self):
        for value in ("012345", " 012 345\n", "012-345", "0 1 2 3 4 5", "012\u00a0345"):
            self.assertEqual(normalize_otp(value), "012345")
        for value in ("12345", "1234567", "abc123456", "１２３４５６", "123_456"):
            self.assertEqual(normalize_otp(value), "")

    def test_alert_has_local_time_and_no_code(self):
        with patch("app.services.authentication.mail.send_email_message", return_value=True) as send:
            send_device_login_alert_email("test@example.invalid", "Chrome trên Windows",
                                         datetime(2026, 11, 18, 6, 0, tzinfo=timezone.utc))
        _, subject, body = send.call_args.args
        self.assertIn("Cảnh báo", subject)
        self.assertIn("13:00:00", body)
        self.assertIn("đổi mật khẩu", body)
        self.assertNotIn("Mã xác minh đăng nhập", body)


if __name__ == "__main__":
    unittest.main()
