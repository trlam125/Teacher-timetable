"""Real row-lock regressions, only against the explicitly named disposable CI DB."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
import secrets
import threading
import time
import unittest

# Establish dummy application settings before importing any project module.
from test_auth_security import request

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.models import AccountDevice, Base, DeviceLoginChallenge, User
from app.routers.auth_routes.password_reset import reset_password
from app.services.authentication import csrf, devices, sessions
from app.services.authentication.credentials import reset_signer


@unittest.skipUnless(os.environ.get("AUTH_TEST_DATABASE_URL"), "Disposable PostgreSQL test database not configured")
class AuthConcurrencyTests(unittest.TestCase):
    def setUp(self):
        url = make_url(os.environ["AUTH_TEST_DATABASE_URL"])
        if url.host not in {"localhost", "127.0.0.1"} or url.database != "smart_tkb_auth_tests":
            raise RuntimeError("Concurrency tests require the dedicated loopback smart_tkb_auth_tests database")
        self.base_engine = create_engine(url)
        self.schema = "auth_test_" + secrets.token_hex(10)
        with self.base_engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = self.base_engine.execution_options(schema_translate_map={None: self.schema})
        Base.metadata.create_all(self.engine, tables=[User.__table__, AccountDevice.__table__, DeviceLoginChallenge.__table__])
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.factory() as db:
            user = User(name="Concurrency", email="concurrency@example.invalid", password_hash="unused", role="teacher")
            db.add(user)
            db.commit()
            self.user_id = user.id

    def tearDown(self):
        with self.base_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        self.base_engine.dispose()

    def test_same_reset_token_succeeds_exactly_once_under_concurrency(self):
        nonce = secrets.token_urlsafe(32)
        with self.factory() as db:
            user = db.get(User, self.user_id)
            user.reset_token_hash = sessions.secret_hash(nonce)
            user.reset_token_expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
            db.commit()
        token = reset_signer.dumps({"uid": self.user_id, "nonce": nonce})
        barrier = threading.Barrier(2)
        def attempt(index):
            with self.factory() as db:
                barrier.wait(timeout=10)
                password = f"new-test-password-{index}"
                return reset_password(token, request(), password, password, db).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(attempt, [1, 2]))
        self.assertEqual(sorted(statuses), [200, 400])
        with self.factory() as db:
            self.assertEqual(db.get(User, self.user_id).session_version, 2)

    def test_simultaneous_verified_browsers_cannot_exceed_two_devices(self):
        with self.factory() as db:
            user = db.get(User, self.user_id)
            db.add(devices._new_device(db, user, secrets.token_urlsafe(32), "Existing device"))
            cookies = []
            for index in range(2):
                browser, token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                db.add(DeviceLoginChallenge(token_hash=sessions.secret_hash(token), user_id=user.id,
                    browser_hash=sessions.secret_hash(browser), session_version=user.session_version,
                    otp_hash="unused-after-verification", label=f"New device {index}",
                    expires_at=int(time.time()) + 600, attempts=0, verified=True))
                cookies.append({sessions.DEVICE_COOKIE: browser, devices.PENDING_COOKIE: token,
                                csrf.CSRF_COOKIE: secrets.token_urlsafe(32)})
            db.commit()
        barrier = threading.Barrier(2)
        def admit(cookie):
            with self.factory() as db:
                req = request(cookie)
                barrier.wait(timeout=10)
                user, challenge, browser = devices.pending_login(req, db)
                response = devices.complete_login(req, db, user, challenge, browser)
                return response.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(admit, cookies))
        self.assertEqual(sorted(statuses), [200, 303])
        with self.factory() as db:
            self.assertEqual(len(db.scalars(select(AccountDevice).where(AccountDevice.user_id == self.user_id)).all()), 2)


if __name__ == "__main__":
    unittest.main()
