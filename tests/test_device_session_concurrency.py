"""Exercise real account-row locks only in the dedicated disposable CI database."""
from concurrent.futures import ThreadPoolExecutor
import os
import secrets
import threading
import time
import unittest

from test_device_session_policy import apply_cookies, request
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.models import AccountDevice, Base, DeviceLoginChallenge, User
from app.services.authentication import devices, sessions


@unittest.skipUnless(os.environ.get("AUTH_TEST_DATABASE_URL"), "Disposable PostgreSQL test database not configured")
class DeviceSessionConcurrencyTests(unittest.TestCase):
    def test_simultaneous_logins_keep_only_two_live_sessions_and_remember_all_browsers(self):
        url = make_url(os.environ["AUTH_TEST_DATABASE_URL"])
        if url.host not in {"localhost", "127.0.0.1"} or url.database != "smart_tkb_auth_tests":
            raise RuntimeError("Use only the dedicated loopback smart_tkb_auth_tests database")
        base_engine = create_engine(url)
        schema = "device_policy_" + secrets.token_hex(10)
        try:
            with base_engine.begin() as conn:
                conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            engine = base_engine.execution_options(schema_translate_map={None: schema})
            Base.metadata.create_all(engine, tables=[User.__table__, AccountDevice.__table__, DeviceLoginChallenge.__table__])
            factory = sessionmaker(bind=engine, expire_on_commit=False)
            with factory() as db:
                user = User(name="Concurrency", email="concurrency@example.invalid", password_hash="unused", role="super_admin")
                db.add(user)
                db.commit()
                user_id = user.id
                for _ in range(2):
                    devices.begin_login(request(), db, user)
            barrier = threading.Barrier(6)
            def admit(_):
                with factory() as db:
                    user = db.get(User, user_id)
                    barrier.wait(timeout=15)
                    response = devices.begin_login(request(), db, user)
                    cookies = {}
                    apply_cookies(cookies, response)
                    return response.status_code, cookies
            with ThreadPoolExecutor(max_workers=6) as pool:
                results = list(pool.map(admit, range(6)))
            self.assertTrue(all(status == 303 for status, _ in results))
            with factory() as db:
                self.assertEqual(len(db.scalars(select(AccountDevice)).all()), 8)
                active = db.scalars(select(AccountDevice).where(AccountDevice.session_hash.is_not(None),
                    AccountDevice.session_expires_at > int(time.time()))).all()
                self.assertEqual(len(active), 2)
                self.assertEqual(sum(sessions.session_user(cookies, db) is not None for _, cookies in results), 2)
        finally:
            with base_engine.begin() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            base_engine.dispose()
