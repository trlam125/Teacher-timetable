"""Offline behavior regressions; all accounts, secrets and storage are disposable."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from http.cookies import SimpleCookie
import os
import secrets
import unittest
from unittest.mock import patch

# Do not inherit a deployment's connection or signing key when running tests.
os.environ["DATABASE_URL"] = "postgresql://test:test@127.0.0.1:1/unused"
os.environ["SECRET_KEY"] = "offline-auth-regression-key-only-never-deploy"
os.environ["APP_ENV"] = "production"
os.environ["APP_BASE_URL"] = "https://testserver"

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.models import AccountDevice, Base, DeviceLoginChallenge, EmailChangeVerification, User
from app.routers.auth_routes import devices as routes, logout, password_reset
from app.services.authentication import csrf, devices, sessions, rate_limits
from app.services.authentication.credentials import email_change_otp_signer, pwd, reset_signer, signer
from app.services.authentication.verification import email_change_otp_hash, reset_account_for_token


def request(cookies=None, origin=None):
    headers = [(b"host", b"testserver"), (b"user-agent", b"Chrome/140 Windows")]
    if cookies:
        headers.append((b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()))
    if origin:
        headers.append((b"origin", origin.encode()))
    return Request({"type": "http", "method": "POST", "scheme": "https",
        "path": "/login", "query_string": b"", "server": ("testserver", 443),
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


class AuthSecurityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool,
                                    connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.factory()
        self.user = User(name="Test Teacher", email="teacher@example.invalid",
                         password_hash="unused", role="teacher")
        self.db.add(self.user)
        self.db.commit()
        self.sent = []
        self.patches = [
            patch.object(rate_limits, "rate_limit_blocked", return_value=False),
            patch.object(rate_limits, "rate_limit_exceeded", return_value=False),
            patch.object(rate_limits, "clear_rate_limit_bucket"),
            patch.object(devices, "rate_limit_exceeded", return_value=False),
            patch.object(devices, "send_device_login_otp_email", side_effect=self.send_otp),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.db.close()
        self.engine.dispose()

    def send_otp(self, email, otp, label):
        self.sent.append(otp)
        return True

    def browser(self):
        return {csrf.CSRF_COOKIE: secrets.token_urlsafe(32)}

    def token(self, cookies):
        return csrf.form_token(request(cookies))[1]

    def start(self, cookies):
        response = devices.begin_login(request(cookies), self.db, self.user)
        apply_cookies(cookies, response)
        return response

    def verify(self, cookies, otp=None):
        response = routes.verify_device(request(cookies), otp or self.sent[-1], self.token(cookies), self.db)
        apply_cookies(cookies, response)
        return response

    def login(self):
        cookies = self.browser()
        self.start(cookies)
        self.verify(cookies)
        return cookies

    def test_new_browser_has_no_session_until_verified_and_challenge_is_one_use(self):
        cookies = self.browser()
        self.assertEqual(self.start(cookies).headers["location"], "/auth/device")
        self.assertNotIn("session", cookies)
        pending = dict(cookies)
        self.verify(cookies)
        self.assertEqual(sessions.session_user(cookies, self.db).id, self.user.id)
        with self.assertRaises(HTTPException) as raised:
            self.verify(pending)
        self.assertEqual(raised.exception.status_code, 401)

    def test_otp_cannot_be_replayed_on_another_browser(self):
        cookies = self.browser()
        self.start(cookies)
        other = dict(cookies, trusted_browser=secrets.token_urlsafe(32))
        with self.assertRaises(HTTPException):
            self.verify(other)
        self.assertEqual(len(devices.device_rows(self.db, self.user.id)), 0)

    def test_five_failed_attempts_prevent_even_the_correct_otp(self):
        cookies = self.browser()
        self.start(cookies)
        wrong = "000000" if self.sent[-1] != "000000" else "111111"
        for _ in range(5):
            self.assertEqual(self.verify(cookies, wrong).status_code, 400)
        with self.assertRaises(HTTPException) as raised:
            self.verify(cookies)
        self.assertEqual(raised.exception.status_code, 429)

    def test_expired_and_credential_stale_challenges_are_rejected(self):
        cookies = self.browser()
        self.start(cookies)
        challenge = self.db.get(DeviceLoginChallenge, sessions.secret_hash(cookies[devices.PENDING_COOKIE]))
        challenge.expires_at = 0
        self.db.commit()
        with self.assertRaises(HTTPException):
            self.verify(cookies)
        self.start(cookies)
        sessions.invalidate_credential_state(self.user)
        self.db.commit()
        with self.assertRaises(HTTPException):
            self.verify(cookies)

    def test_third_browser_must_choose_own_device_and_revokes_only_that_device(self):
        first, second = self.login(), self.login()
        third = self.browser()
        self.start(third)
        with self.assertRaises(HTTPException):
            routes.choose_device(request(third), "anything", self.token(third), self.db)
        self.assertEqual(self.verify(third).context["mode"], "choose")
        self.assertNotIn("session", third)
        response = routes.choose_device(request(third), "another-accounts-device", self.token(third), self.db)
        self.assertEqual(response.context["mode"], "choose")
        self.assertEqual(len(devices.device_rows(self.db, self.user.id)), 2)
        old_id = signer.loads(first["session"])["did"]
        response = routes.choose_device(request(third), old_id, self.token(third), self.db)
        apply_cookies(third, response)
        self.assertEqual(len(devices.device_rows(self.db, self.user.id)), 2)
        self.assertIsNone(sessions.session_user(first, self.db))
        self.assertIsNotNone(sessions.session_user(second, self.db))
        self.assertIsNotNone(sessions.session_user(third, self.db))

    def test_cancel_or_logout_invalidates_verified_pending_challenge(self):
        first, second = self.login(), self.login()
        for cancel in (routes.cancel_device_login, logout.logout):
            with self.subTest(cancel=cancel.__name__):
                third = self.browser()
                self.start(third)
                self.assertEqual(self.verify(third).context["mode"], "choose")
                copied = dict(third)
                cancel(request(third), self.token(third), self.db)
                with self.assertRaises(HTTPException) as raised:
                    routes.choose_device(request(copied), "unused", self.token(copied), self.db)
                self.assertEqual(raised.exception.status_code, 401)
                self.assertEqual(len(devices.device_rows(self.db, self.user.id)), 2)
                self.assertIsNotNone(sessions.session_user(first, self.db))
                self.assertIsNotNone(sessions.session_user(second, self.db))

    def test_password_confirmation_obeys_login_lockout(self):
        with patch.object(rate_limits, "rate_limit_blocked", return_value=True), \
             patch.object(rate_limits.pwd, "verify") as password_check:
            with self.assertRaises(HTTPException) as raised:
                rate_limits.verify_sensitive_password(request(), self.user, "guess")
            self.assertEqual(raised.exception.status_code, 429)
            password_check.assert_not_called()

    def test_wrong_confirmation_updates_shared_login_buckets(self):
        with patch.object(rate_limits.pwd, "verify", return_value=False), \
             patch.object(rate_limits, "rate_limit_exceeded", return_value=False) as counter:
            self.assertFalse(rate_limits.verify_sensitive_password(request(), self.user, "wrong"))
            self.assertEqual({call.args[0] for call in counter.call_args_list}, {"login_email", "login_ip"})

    def test_logout_revokes_copied_cookie_and_preserves_other_browser(self):
        first, second = self.login(), self.login()
        stolen = dict(first)
        logout.logout(request(first), self.token(first), self.db)
        self.assertIsNone(sessions.session_user(stolen, self.db))
        self.assertIsNotNone(sessions.session_user(second, self.db))
        # A trusted browser still needs credentials, but need not repeat email OTP.
        sent_before = len(self.sent)
        self.start(first)
        self.assertEqual(len(self.sent), sent_before)
        self.assertIsNotNone(sessions.session_user(first, self.db))

    def test_new_login_rotates_session_and_legacy_cookies_fail_closed(self):
        cookies = self.login()
        previous = dict(cookies)
        self.start(cookies)
        self.assertIsNone(sessions.session_user(previous, self.db))
        legacy = {"session": signer.dumps({"uid": self.user.id, "sv": self.user.session_version})}
        self.assertIsNone(sessions.session_user(legacy, self.db))

    def reset_token(self):
        nonce = secrets.token_urlsafe(32)
        self.user.reset_token_hash = sessions.secret_hash(nonce)
        self.user.reset_token_expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        self.db.commit()
        return reset_signer.dumps({"uid": self.user.id, "nonce": nonce})

    def test_credential_changes_revoke_reset_link_and_existing_sessions(self):
        cookies = self.login()
        token = self.reset_token()
        self.assertIsNotNone(reset_account_for_token(token, self.db))
        sessions.invalidate_credential_state(self.user)
        self.db.commit()
        self.assertIsNone(reset_account_for_token(token, self.db))
        self.assertIsNone(sessions.session_user(cookies, self.db))

    def test_consumed_reset_link_cannot_be_used_again(self):
        token = self.reset_token()
        response = password_reset.reset_password(token, request(), "new-test-password", "new-test-password", self.db)
        self.assertEqual(response.status_code, 200)
        response = password_reset.reset_password(token, request(), "other-test-password", "other-test-password", self.db)
        self.assertEqual(response.status_code, 400)

    def test_real_password_change_revokes_old_links_and_refreshes_only_current_browser(self):
        from app.routers import teacher
        self.user.password_hash = pwd.hash("original-test-password")
        self.db.commit()
        first, second = self.login(), self.login()
        old = dict(first)
        token = self.reset_token()
        response = teacher.update_teacher_password(request(first), "original-test-password",
            "updated-test-password", "updated-test-password", None, self.user, self.db)
        apply_cookies(first, response)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(reset_account_for_token(token, self.db))
        self.assertIsNone(sessions.session_user(old, self.db))
        self.assertIsNone(sessions.session_user(second, self.db))
        self.assertIsNotNone(sessions.session_user(first, self.db))

    def test_real_email_change_revokes_reset_link_and_keeps_current_browser(self):
        from app.routers.auth_routes import email_change
        cookies = self.login()
        token = self.reset_token()
        nonce, otp = secrets.token_urlsafe(32), "123456"
        new_email = "new-email@example.invalid"
        verification = EmailChangeVerification(user_id=self.user.id, requested_by_user_id=self.user.id,
            new_email=new_email, otp_hash=email_change_otp_hash(self.user.id, new_email, otp),
            token_hash=sessions.secret_hash(nonce), attempt_count=0,
            expires_at=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat())
        self.db.add(verification)
        self.db.commit()
        proof = email_change_otp_signer.dumps({"id": verification.id, "nonce": nonce})
        response = email_change.verify_email_change(request(cookies), proof, otp, self.user, self.db)
        apply_cookies(cookies, response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.user.email, new_email)
        self.assertIsNone(reset_account_for_token(token, self.db))
        self.assertIsNotNone(sessions.session_user(cookies, self.db))

    def test_waiting_admin_password_request_cannot_restore_logged_out_session(self):
        from app.routers import admin
        self.user.role = "super_admin"
        self.db.commit()
        cookies = self.login()
        old_hash = self.user.password_hash
        # Model the request that passed current_user before logout won the lock.
        stale_actor = self.user
        logout.logout(request(cookies), self.token(cookies), self.db)
        with self.assertRaises(HTTPException) as raised:
            admin.update_account(account_id=self.user.id, request=request(cookies), name=self.user.name,
                password="attempted-password", profile_url="", avatar_file=None, remove_avatar=False,
                user=stale_actor, db=self.db)
        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(self.user.password_hash, old_hash)
        self.assertIsNone(sessions.session_user(cookies, self.db))

    def test_google_login_cannot_skip_new_device_verification(self):
        from app.routers import social_auth
        cookies = self.browser()
        response = social_auth.finish(self.db, self.user, request(cookies))
        self.assertEqual(response.headers["location"], "/auth/device")
        self.assertNotIn("session=", "\n".join(response.headers.getlist("set-cookie")))

    def test_csrf_rejects_missing_token_other_browser_and_foreign_origin(self):
        cookies = self.browser()
        token = self.token(cookies)
        csrf.require_form_token(request(cookies, "https://testserver"), token)
        csrf.require_form_token(request(cookies, "https://testserver:443"), token)
        for req, value in [(request(cookies), ""), (request(self.browser()), token),
                           (request(cookies, "https://attacker.invalid"), token)]:
            with self.assertRaises(HTTPException) as raised:
                csrf.require_form_token(req, value)
            self.assertEqual(raised.exception.status_code, 403)

    def test_login_route_rejects_cross_site_form_before_checking_credentials(self):
        from app.routers.auth_routes import login
        cookies = self.browser()
        with patch.object(login, "rate_limit_blocked") as limiter:
            with self.assertRaises(HTTPException) as raised:
                login.login(request(cookies, "https://attacker.invalid"), self.user.email,
                            "attacker-known-password", self.token(cookies), self.db)
            self.assertEqual(raised.exception.status_code, 403)
            limiter.assert_not_called()

    def test_forgot_password_has_same_public_result_for_unknown_email(self):
        with patch.object(password_reset, "rate_limit_exceeded", return_value=False), \
             patch.object(password_reset, "captcha_is_valid", return_value=True), \
             patch.object(password_reset, "new_captcha", return_value=({}, "captcha")), \
             patch.object(password_reset, "email_delivery_configured", return_value=True), \
             patch.object(password_reset, "public_base_url", return_value="https://testserver"), \
             patch.object(password_reset, "development_reset_links_enabled", return_value=False):
            results = []
            for email in [self.user.email, "missing@example.invalid"]:
                response = password_reset.forgot_password(request(), BackgroundTasks(), email, "yes", "ok", "token", self.db)
                results.append((response.status_code, response.context["submitted"],
                                response.context["error"], response.context["dev_reset_link"]))
            self.assertEqual(results, [(200, True, None, None)] * 2)

    def test_failed_old_email_cannot_erase_new_reset_token(self):
        self.reset_token()
        old_hash = self.user.reset_token_hash
        self.reset_token()
        new_hash = self.user.reset_token_hash
        with patch.object(password_reset, "send_password_reset_email", return_value=False), \
             patch.object(password_reset, "SessionLocal", self.factory):
            password_reset._deliver_reset_email(self.user.email, "https://testserver/reset", self.user.id, old_hash)
        self.db.expire_all()
        self.assertEqual(self.db.get(User, self.user.id).reset_token_hash, new_hash)

    def test_admin_avatar_confirmation_treats_teacher_name_as_text(self):
        from app.routers import admin
        self.user.role = "super_admin"
        attacker = User(name="'+alert(1)+'", email="untrusted@example.invalid", password_hash="unused",
                        role="teacher", avatar_url="/account/avatar/2")
        self.db.add(attacker)
        self.db.commit()
        with patch.object(admin.realtime_manager, "online_user_ids_for", return_value=[]):
            response = admin.admin_users(request(), self.user, self.db)
        class Buttons(HTMLParser):
            def __init__(self):
                super().__init__()
                self.found = []
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "button" and "data-confirm-message" in attrs:
                    self.found.append(attrs)
        parser = Buttons()
        parser.feed(response.body.decode())
        self.assertEqual(len(parser.found), 1)
        self.assertIn(attacker.name, parser.found[0]["data-confirm-message"])
        self.assertFalse(any(key.startswith("on") for key in parser.found[0]))


if __name__ == "__main__":
    unittest.main()
