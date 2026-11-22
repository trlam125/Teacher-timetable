import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

import test_ai_slides as fixtures


@unittest.skipUnless(os.getenv("AUTH_TEST_DATABASE_URL"), "Set AUTH_TEST_DATABASE_URL to a disposable PostgreSQL database.")
class StudioPostgresTests(fixtures.StudioTests):
    def setUp(self):
        from app.services.ai_slides.models import StudioBase
        from unittest.mock import patch
        from types import SimpleNamespace
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        self.enterContext(patch.dict(os.environ, {
            "AI_SLIDES_ENABLED": "true", "AI_SLIDES_MAX_REQUESTS_PER_USER_DAY": "8",
            "AI_SLIDES_MAX_REQUESTS_SERVER_DAY": "40",
        }))
        self.raw_engine = create_engine(os.environ["AUTH_TEST_DATABASE_URL"])
        self.schema = "studio_test_" + uuid4().hex
        with self.raw_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = self.raw_engine.execution_options(schema_translate_map={None: self.schema})
        self.addCleanup(self.cleanup_schema)
        StudioBase.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)
        self.user = SimpleNamespace(id=1, role="teacher", name="Test Teacher", avatar_url="", email="teacher@example.test")
        self.app = FastAPI(dependencies=[Depends(self.csrf)])
        self.app.include_router(self.routes.router)
        self.app.add_exception_handler(self.routes.provider.StudioError, self.routes.studio_exception_handler)
        self.app.dependency_overrides[self.routes.current_user] = lambda: self.user
        self.app.dependency_overrides[self.routes.db_session] = self.session
        self.client = self.enterContext(TestClient(self.app, base_url="https://testserver"))
        page = self.client.get("/ai-studio")
        self.assertEqual(page.status_code, 200)
        self.client.headers["X-CSRF-Token"] = page.text.split('name="csrf-token" content="', 1)[1].split('"', 1)[0]

    def cleanup_schema(self):
        # This random test-owned schema was created by setUp in the explicitly
        # supplied disposable test database. No application schema is touched.
        with self.raw_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        self.raw_engine.dispose()

    def test_two_concurrent_keys_claim_only_one_provider_slot(self):
        from app.services.ai_slides.models import Deck, Quota, Step
        from app.services.ai_slides.schemas import Profile
        from app.services.ai_slides.state import claim
        from app.services.ai_slides.provider import StudioError
        with self.session_factory() as db:
            deck = Deck(owner_id=1, title="Concurrent test", profile=Profile.model_validate(fixtures.PROFILE).model_dump())
            db.add(deck)
            db.commit()
            deck_id = deck.id
        barrier = threading.Barrier(2)

        def attempt(key):
            with self.session_factory() as db:
                deck = db.get(Deck, deck_id)
                barrier.wait(timeout=10)
                try:
                    return bool(claim(db, deck, "plan", key, 1))
                except StudioError:
                    db.rollback()
                    return False

        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(attempt, key) for key in ("parallel-key-1", "parallel-key-2")]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(sorted(results), [False, True])
        with self.session_factory() as db:
            self.assertEqual(len(db.scalars(select(Step)).all()), 1)
            self.assertTrue(all(row.requests == 1 for row in db.scalars(select(Quota))))

    def test_late_result_cannot_release_a_replacement_lease(self):
        from app.services.ai_slides.models import Deck
        from app.services.ai_slides.state import claim, finish_guard
        with self.session_factory() as db:
            deck = Deck(owner_id=1, title="Late result test", profile=fixtures.PROFILE)
            db.add(deck)
            db.commit()
            first = claim(db, deck, "plan", "expired-first-key", 1)
            deck.lease_until = 0
            db.commit()
            second = claim(db, deck, "plan", "replacement-key", 1)
            with self.assertRaises(self.routes.provider.StudioError):
                finish_guard(db, deck.id, first.id, 1)
            db.rollback()
            self.assertEqual(db.get(Deck, deck.id).active_token, second.id)
