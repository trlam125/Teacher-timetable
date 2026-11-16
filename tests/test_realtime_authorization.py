"""Real chat transactions against a disposable, in-memory SQLite fixture."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker


def setUpModule():
    global models, events, manager, environment
    environment = patch.dict("os.environ", {
        "DATABASE_URL": "postgresql://test:test@127.0.0.1:1/test",
        "SECRET_KEY": "test-only-secret-not-for-production-0123456789",
    })
    environment.start()
    with patch("dotenv.load_dotenv", return_value=False):
        from app import models
        from app.services.realtime import events, manager


def tearDownModule():
    environment.stop()


class ChatAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        models.Base.metadata.create_all(self.engine, tables=[
            models.User.__table__, models.School.__table__, models.UserSchool.__table__,
            models.ChatMessage.__table__, models.RealtimeConnection.__table__,
        ])
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.events_patch = patch.object(events, "SessionLocal", self.sessions)
        self.events_patch.start()
        self.addCleanup(self.events_patch.stop)
        with self.sessions.begin() as db:
            db.add_all([
                models.User(id=i, email=f"test{i}@example.invalid", password_hash="dummy", name=f"User {i}",
                            role="super_admin" if i == 4 else "teacher", session_version=1)
                for i in (1, 2, 3, 4)
            ])
            db.add_all([models.School(id=1, name="School A"), models.School(id=2, name="School B")])
            db.add_all([models.UserSchool(user_id=1, school_id=1),
                        models.UserSchool(user_id=2, school_id=1),
                        models.UserSchool(user_id=3, school_id=2)])
            db.add_all([
                models.ChatMessage(id=1, school_id=1, user_id=1, content="alice text"),
                models.ChatMessage(id=2, school_id=1, user_id=2, content="bob text"),
                models.ChatMessage(id=3, school_id=2, user_id=3, content="private school B"),
            ])

    def event(self, payload, user_id=1, version=1):
        return events.handle_event(user_id, version, payload, "dummy-connection")

    def test_member_send_persists_and_targets_only_school_members(self):
        action = self.event({"type": "chat_send", "school_id": 1, "content": "hello", "client_id": "test-1"})[0]
        self.assertEqual(action[0], "broadcast")
        self.assertEqual(action[2], {1, 2, 4})
        self.assertEqual(action[1]["client_id"], "test-1")
        with self.sessions() as db:
            self.assertEqual(db.get(models.ChatMessage, action[1]["message"]["id"]).content, "hello")

    def test_send_to_another_school_is_rejected_without_writing(self):
        actions = self.event({"type": "chat_send", "school_id": 2, "content": "forbidden"})
        self.assertEqual(actions[0][0], "send")
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(models.ChatMessage)), 3)

    def test_editing_another_members_message_is_rejected(self):
        actions = self.event({"type": "chat_edit", "message_id": 2, "content": "forbidden"})
        self.assertEqual(actions[0][0], "send")
        with self.sessions() as db:
            self.assertEqual(db.get(models.ChatMessage, 2).content, "bob text")

    def test_deleting_another_members_message_is_rejected(self):
        actions = self.event({"type": "chat_delete", "message_id": 2})
        self.assertEqual(actions[0][0], "send")
        with self.sessions() as db:
            self.assertIsNone(db.get(models.ChatMessage, 2).deleted_at)

    def test_owner_can_edit_and_delete_own_message(self):
        edited = self.event({"type": "chat_edit", "message_id": 1, "content": "updated"})
        self.assertEqual(edited[0][1]["type"], "chat_message_updated")
        deleted = self.event({"type": "chat_delete", "message_id": 1})
        self.assertEqual(deleted[0][1]["type"], "chat_message_deleted")
        with self.sessions() as db:
            row = db.get(models.ChatMessage, 1)
            self.assertEqual(row.content, "")
            self.assertIsNotNone(row.deleted_at)

    def test_reply_cannot_reference_a_message_from_another_school(self):
        actions = self.event({"type": "chat_send", "school_id": 1, "content": "reply", "reply_to_id": 3})
        self.assertEqual(actions[0][0], "send")
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(models.ChatMessage)), 3)

    def test_revoked_session_is_closed_before_writing(self):
        actions = self.event({"type": "chat_send", "school_id": 1, "content": "forbidden"}, version=0)
        self.assertEqual(actions, [("close", 4401)])

    def test_connection_cap_counts_other_manager_records_and_recovers_after_close(self):
        first, second = manager.RealtimeConnectionManager(), manager.RealtimeConnectionManager()
        # SQLite cannot exercise PostgreSQL advisory locks. This checks shared
        # record accounting only; concurrent admission still needs PostgreSQL.
        with (patch.object(manager, "SessionLocal", self.sessions),
              patch.object(manager, "WS_MAX_CONNECTIONS_PER_USER", 8),
              patch.object(manager.RealtimeConnectionManager, "_lock_user_presence", return_value=None)):
            for i in range(8):
                owner = first if i % 2 == 0 else second
                owner.add(1, f"connection-{i}", object())
            with self.assertRaises(manager.ConnectionLimitExceeded):
                second.add(1, "rejected", object())
            self.assertNotIn("rejected", second._connections.get(1, {}))
            first.remove(1, "connection-0")
            second.add(1, "replacement", object())
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(models.RealtimeConnection)), 8)


if __name__ == "__main__":
    unittest.main()
