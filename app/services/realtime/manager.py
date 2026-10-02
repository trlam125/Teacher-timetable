from __future__ import annotations

from app.services.foundation import *
from app.services.web import *
from app.services.auth import *
from .utils import _utc_now_iso


class RealtimeConnectionManager:
    """Realtime registry shared across Uvicorn workers through PostgreSQL."""

    CHANNEL = "smart_tkb_realtime_v1"
    PRESENCE_TTL_SECONDS = 180
    PRESENCE_LOCK_BASE = 73120270000
    EVENT_TTL_SECONDS = 24 * 60 * 60
    EVENT_CLEANUP_INTERVAL_SECONDS = 5 * 60
    MAX_INLINE_NOTIFY_BYTES = 7000
    SESSION_CHECK_INTERVAL_SECONDS = 15
    SEND_TIMEOUT_SECONDS = 2.0

    def __init__(self):
        self._lock = threading.RLock()
        self._connections: dict[int, dict[str, WebSocket]] = defaultdict(dict)
        self._send_locks: dict[str, asyncio.Lock] = {}
        self._instance_id = secrets.token_hex(12)
        self._listener_started = False
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._last_event_cleanup_at = 0.0
        self._psycopg_dsn = DATABASE_URL.replace(
            "postgresql+psycopg://", "postgresql://", 1
        )

    def _presence_cutoff(self) -> str:
        return (
            datetime.now(timezone.utc) - timedelta(seconds=self.PRESENCE_TTL_SECONDS)
        ).isoformat(timespec="seconds")

    def _lock_user_presence(self, db: Session, user_id: int) -> None:
        db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": self.PRESENCE_LOCK_BASE + int(user_id)},
        )

    def _cleanup_stale_presence(self, db: Session) -> None:
        db.execute(
            delete(RealtimeConnection).where(
                RealtimeConnection.updated_at < self._presence_cutoff()
            )
        )

    def _ensure_listener(self, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self._event_loop = loop
            if self._listener_started:
                return
            self._listener_started = True
        threading.Thread(
            target=self._listen_for_remote_events,
            name=f"realtime-listener-{self._instance_id[:8]}",
            daemon=True,
        ).start()

    def _listen_for_remote_events(self) -> None:
        while True:
            try:
                with psycopg.connect(self._psycopg_dsn, autocommit=True) as conn:
                    conn.execute(f"LISTEN {self.CHANNEL}")
                    for notification in conn.notifies():
                        try:
                            envelope = self._notification_envelope(notification.payload)
                        except (TypeError, ValueError, json.JSONDecodeError):
                            continue
                        if not envelope or envelope.get("source") == self._instance_id:
                            continue
                        payload = envelope.get("payload")
                        if not isinstance(payload, dict):
                            continue
                        exclude_user_id = envelope.get("exclude_user_id")
                        only_raw = envelope.get("only_user_ids")
                        only_user_ids = (
                            {int(value) for value in only_raw}
                            if isinstance(only_raw, list)
                            else None
                        )
                        with self._lock:
                            loop = self._event_loop
                        if loop is None or loop.is_closed():
                            continue
                        asyncio.run_coroutine_threadsafe(
                            self._broadcast_local(
                                payload,
                                exclude_user_id=(
                                    int(exclude_user_id)
                                    if exclude_user_id is not None
                                    else None
                                ),
                                only_user_ids=only_user_ids,
                            ),
                            loop,
                        )
            except Exception:
                logger.exception("PostgreSQL realtime listener stopped; reconnecting.")
                time.sleep(2)

    def _notification_envelope(self, raw: str) -> dict | None:
        notice = json.loads(raw)
        if not isinstance(notice, dict):
            return None
        if notice.get("source") == self._instance_id:
            return None
        event_id = notice.get("event_id")
        if event_id is None:
            # Accept notifications sent by an older worker during restart.
            return notice
        if not isinstance(event_id, str) or len(event_id) > 64:
            return None
        with SessionLocal() as db:
            event = db.get(RealtimeEvent, event_id)
            if event is None or event.expires_at <= int(time.time()):
                return None
            envelope = json.loads(event.envelope_json)
        return envelope if isinstance(envelope, dict) else None

    def _publish_sync(
        self,
        payload: dict,
        exclude_user_id: int | None,
        only_user_ids: set[int] | None,
    ) -> None:
        if only_user_ids is not None and not only_user_ids:
            return

        now = int(time.time())
        envelope = json.dumps(
            {
                "source": self._instance_id,
                "payload": payload,
                "exclude_user_id": exclude_user_id,
                "only_user_ids": (
                    sorted(int(uid) for uid in only_user_ids)
                    if only_user_ids is not None
                    else None
                ),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

        monotonic_now = time.monotonic()
        with self._lock:
            cleanup_due = (
                monotonic_now - self._last_event_cleanup_at
                >= self.EVENT_CLEANUP_INTERVAL_SECONDS
            )
            if cleanup_due:
                self._last_event_cleanup_at = monotonic_now

        # PostgreSQL NOTIFY accepts payloads below 8 KB. Ordinary chat, typing
        # and presence events are much smaller, so send them inline and avoid
        # INSERT + remote SELECT entirely. Large future events retain the table
        # fallback for compatibility.
        inline = len(envelope.encode("utf-8")) <= self.MAX_INLINE_NOTIFY_BYTES
        with engine.begin() as connection:
            if cleanup_due:
                connection.execute(
                    delete(RealtimeEvent).where(RealtimeEvent.expires_at <= now)
                )

            if inline:
                notification_payload = envelope
            else:
                event_id = secrets.token_hex(16)
                connection.execute(
                    RealtimeEvent.__table__.insert().values(
                        id=event_id,
                        envelope_json=envelope,
                        expires_at=now + self.EVENT_TTL_SECONDS,
                    )
                )
                notification_payload = json.dumps(
                    {"source": self._instance_id, "event_id": event_id},
                    separators=(",", ":"),
                )

            connection.exec_driver_sql(
                "SELECT pg_notify(%s, %s)",
                (self.CHANNEL, notification_payload),
            )

    def add(self, user_id: int, connection_id: str, websocket: WebSocket) -> bool:
        try:
            self._ensure_listener(asyncio.get_running_loop())
        except RuntimeError:
            pass
        with self._lock:
            self._connections[user_id][connection_id] = websocket
            self._send_locks[connection_id] = asyncio.Lock()

        now = _utc_now_iso()
        db = SessionLocal()
        try:
            self._lock_user_presence(db, user_id)
            self._cleanup_stale_presence(db)
            was_offline = (
                db.scalar(
                    select(RealtimeConnection.connection_id)
                    .where(
                        RealtimeConnection.user_id == user_id,
                        RealtimeConnection.updated_at >= self._presence_cutoff(),
                    )
                    .limit(1)
                )
                is None
            )
            db.merge(
                RealtimeConnection(
                    connection_id=connection_id,
                    user_id=user_id,
                    instance_id=self._instance_id,
                    updated_at=now,
                )
            )
            db.commit()
            return was_offline
        except Exception:
            db.rollback()
            logger.exception("Could not register shared realtime presence.")
            with self._lock:
                return len(self._connections.get(user_id, {})) == 1
        finally:
            db.close()

    def touch(self, user_id: int, connection_id: str) -> None:
        db = SessionLocal()
        try:
            row = db.get(RealtimeConnection, connection_id)
            if row and row.user_id == user_id and row.instance_id == self._instance_id:
                row.updated_at = _utc_now_iso()
                db.commit()
        except Exception:
            db.rollback()
            logger.exception("Could not refresh shared realtime presence.")
        finally:
            db.close()

    def remove(self, user_id: int, connection_id: str) -> bool:
        with self._lock:
            sockets = self._connections.get(user_id)
            if sockets:
                sockets.pop(connection_id, None)
                if not sockets:
                    self._connections.pop(user_id, None)
            self._send_locks.pop(connection_id, None)

        db = SessionLocal()
        try:
            self._lock_user_presence(db, user_id)
            row = db.get(RealtimeConnection, connection_id)
            if row and row.user_id == user_id and row.instance_id == self._instance_id:
                db.delete(row)
            self._cleanup_stale_presence(db)
            still_online = (
                db.scalar(
                    select(RealtimeConnection.connection_id)
                    .where(
                        RealtimeConnection.user_id == user_id,
                        RealtimeConnection.updated_at >= self._presence_cutoff(),
                    )
                    .limit(1)
                )
                is not None
            )
            db.commit()
            return not still_online
        except Exception:
            db.rollback()
            logger.exception("Could not remove shared realtime presence.")
            return False
        finally:
            db.close()

    def is_online(self, user_id: int) -> bool:
        return bool(self.online_user_ids_for({user_id}))

    def online_user_ids(self) -> list[int]:
        db = SessionLocal()
        try:
            return sorted(
                set(
                    db.scalars(
                        select(RealtimeConnection.user_id)
                        .where(RealtimeConnection.updated_at >= self._presence_cutoff())
                        .distinct()
                    ).all()
                )
            )
        finally:
            db.close()

    def online_count(self) -> int:
        return len(self.online_user_ids())

    def online_user_ids_for(self, allowed_user_ids: set[int]) -> list[int]:
        if not allowed_user_ids:
            return []
        db = SessionLocal()
        try:
            return sorted(
                set(
                    db.scalars(
                        select(RealtimeConnection.user_id)
                        .where(
                            RealtimeConnection.updated_at >= self._presence_cutoff(),
                            RealtimeConnection.user_id.in_(allowed_user_ids),
                        )
                        .distinct()
                    ).all()
                )
            )
        finally:
            db.close()

    def online_count_for(self, allowed_user_ids: set[int]) -> int:
        return len(self.online_user_ids_for(allowed_user_ids))

    async def _broadcast_local(
        self,
        payload: dict,
        exclude_user_id: int | None = None,
        only_user_ids: set[int] | None = None,
    ) -> None:
        """Deliver to local sockets concurrently.

        Session revocation is checked by each socket loop (on incoming events and
        every SESSION_CHECK_INTERVAL_SECONDS while idle), so broadcasting must not
        re-query every connected account. A slow client is isolated by a timeout
        instead of blocking delivery to every socket behind it.
        """
        with self._lock:
            targets = [
                (uid, cid, ws, self._send_locks.get(cid))
                for uid, sockets in self._connections.items()
                if (exclude_user_id is None or uid != exclude_user_id)
                and (only_user_ids is None or uid in only_user_ids)
                for cid, ws in sockets.items()
            ]
        if not targets:
            return

        async def send_one(
            uid: int, cid: str, ws: WebSocket, send_lock: asyncio.Lock | None
        ):
            try:
                if send_lock is None:
                    await asyncio.wait_for(
                        ws.send_json(payload), timeout=self.SEND_TIMEOUT_SECONDS
                    )
                else:
                    async with send_lock:
                        await asyncio.wait_for(
                            ws.send_json(payload), timeout=self.SEND_TIMEOUT_SECONDS
                        )
                return None
            except Exception:
                return (uid, cid)

        results = await asyncio.gather(
            *(send_one(uid, cid, ws, send_lock) for uid, cid, ws, send_lock in targets),
            return_exceptions=False,
        )
        dead = [item for item in results if item is not None]
        if dead:
            await asyncio.gather(
                *(asyncio.to_thread(self.remove, uid, cid) for uid, cid in dead),
                return_exceptions=True,
            )

    async def broadcast(
        self,
        payload: dict,
        exclude_user_id: int | None = None,
        only_user_ids: set[int] | None = None,
    ) -> None:
        """Broadcast locally and publish cross-worker at the same time."""
        local_delivery = self._broadcast_local(payload, exclude_user_id, only_user_ids)
        remote_publish = asyncio.to_thread(
            self._publish_sync, payload, exclude_user_id, only_user_ids
        )
        local_result, remote_result = await asyncio.gather(
            local_delivery, remote_publish, return_exceptions=True
        )
        if isinstance(local_result, Exception):
            logger.error(
                "Could not deliver realtime event to local sockets: %s", local_result
            )
        if isinstance(remote_result, Exception):
            logger.error(
                "Could not publish realtime event through PostgreSQL: %s", remote_result
            )


realtime_manager = RealtimeConnectionManager()

__all__ = [name for name in globals() if not name.startswith("__")]
