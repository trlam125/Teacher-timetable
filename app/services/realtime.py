from __future__ import annotations

from app.services.foundation import *
from app.services.web import *
from app.services.auth import *

class RealtimeConnectionManager:
    """Realtime registry shared across Uvicorn workers through PostgreSQL."""

    CHANNEL = "smart_tkb_realtime_v1"
    PRESENCE_TTL_SECONDS = 180
    PRESENCE_LOCK_BASE = 73120270000
    EVENT_TTL_SECONDS = 24 * 60 * 60
    SESSION_CHECK_INTERVAL_SECONDS = 15

    def __init__(self):
        self._lock = threading.RLock()
        self._connections: dict[int, dict[str, WebSocket]] = defaultdict(dict)
        self._instance_id = secrets.token_hex(12)
        self._listener_started = False
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._psycopg_dsn = DATABASE_URL.replace(
            "postgresql+psycopg://", "postgresql://", 1
        )

    def _presence_cutoff(self) -> str:
        return (
            datetime.now(timezone.utc)
            - timedelta(seconds=self.PRESENCE_TTL_SECONDS)
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
        event_id = secrets.token_hex(16)
        envelope = json.dumps(
            {
                "source": self._instance_id,
                "payload": payload,
                "exclude_user_id": exclude_user_id,
                "only_user_ids": (
                    sorted(int(uid) for uid in only_user_ids)
                    if only_user_ids is not None else None
                ),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        # Insert and notify in one transaction: another worker must never see
        # a notification before the complete event has been committed.
        with engine.begin() as connection:
            connection.execute(
                delete(RealtimeEvent).where(RealtimeEvent.expires_at <= now)
            )
            connection.execute(
                RealtimeEvent.__table__.insert().values(
                    id=event_id,
                    envelope_json=envelope,
                    expires_at=now + self.EVENT_TTL_SECONDS,
                )
            )
            connection.exec_driver_sql(
                "SELECT pg_notify(%s, %s)",
                (self.CHANNEL, json.dumps({"source": self._instance_id, "event_id": event_id})),
            )

    def add(self, user_id: int, connection_id: str, websocket: WebSocket) -> bool:
        try:
            self._ensure_listener(asyncio.get_running_loop())
        except RuntimeError:
            pass
        with self._lock:
            self._connections[user_id][connection_id] = websocket

        now = _utc_now_iso()
        db = SessionLocal()
        try:
            self._lock_user_presence(db, user_id)
            self._cleanup_stale_presence(db)
            was_offline = db.scalar(
                select(RealtimeConnection.connection_id)
                .where(
                    RealtimeConnection.user_id == user_id,
                    RealtimeConnection.updated_at >= self._presence_cutoff(),
                )
                .limit(1)
            ) is None
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

        db = SessionLocal()
        try:
            self._lock_user_presence(db, user_id)
            row = db.get(RealtimeConnection, connection_id)
            if row and row.user_id == user_id and row.instance_id == self._instance_id:
                db.delete(row)
            self._cleanup_stale_presence(db)
            still_online = db.scalar(
                select(RealtimeConnection.connection_id)
                .where(
                    RealtimeConnection.user_id == user_id,
                    RealtimeConnection.updated_at >= self._presence_cutoff(),
                )
                .limit(1)
            ) is not None
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
        with self._lock:
            targets = [
                (uid, cid, ws)
                for uid, sockets in self._connections.items()
                if (exclude_user_id is None or uid != exclude_user_id)
                and (only_user_ids is None or uid in only_user_ids)
                for cid, ws in sockets.items()
            ]
        dead: list[tuple[int, str]] = []
        if not targets:
            return
        valid_connections = await asyncio.to_thread(valid_realtime_connections, targets)
        for uid, cid, ws in targets:
            if cid not in valid_connections:
                # Let realtime_socket's finally block remove presence and
                # announce offline, rather than removing it twice here.
                try:
                    await ws.close(code=4401)
                except Exception:
                    pass
                continue
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append((uid, cid))
        for uid, cid in dead:
            self.remove(uid, cid)

    async def broadcast(
        self,
        payload: dict,
        exclude_user_id: int | None = None,
        only_user_ids: set[int] | None = None,
    ) -> None:
        await self._broadcast_local(payload, exclude_user_id, only_user_ids)
        try:
            await asyncio.to_thread(
                self._publish_sync, payload, exclude_user_id, only_user_ids
            )
        except Exception:
            logger.exception("Could not publish realtime event through PostgreSQL.")

realtime_manager = RealtimeConnectionManager()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def touch_user_last_seen(user_id: int, min_interval_seconds: int = 0) -> str:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="seconds")
    db = SessionLocal()
    try:
        account = db.get(User, user_id)
        if not account:
            return now_iso
        if min_interval_seconds > 0:
            previous = _parse_iso_datetime(account.last_seen)
            if previous is not None and (now - previous).total_seconds() < min_interval_seconds:
                return account.last_seen or now_iso
        account.last_seen = now_iso
        db.commit()
        return now_iso
    finally:
        db.close()

def valid_realtime_connections(targets: list[tuple[int, str, WebSocket]]) -> set[str]:
    """Check cookie expiry and current account versions before every broadcast.

    Cache accounts only within this call so a password change on any worker
    takes effect on the next delivery, including receive-only connections.
    """
    valid: set[str] = set()
    accounts: dict[int, User | None] = {}
    with SessionLocal() as db:
        for user_id, connection_id, websocket in targets:
            raw = websocket.cookies.get("session")
            if not raw:
                continue
            try:
                data = signer.loads(raw, max_age=SESSION_TTL_SECONDS)
                if int(data["uid"]) != user_id:
                    continue
                if user_id not in accounts:
                    accounts[user_id] = db.get(User, user_id)
                account = accounts[user_id]
                if account and int(data.get("sv", -1)) == account.session_version:
                    valid.add(connection_id)
            except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
                continue
    return valid

def websocket_session_user(websocket: WebSocket) -> User | None:
    raw = websocket.cookies.get("session")
    if not raw:
        return None
    db = SessionLocal()
    try:
        data = signer.loads(raw, max_age=SESSION_TTL_SECONDS)
        account = db.get(User, int(data["uid"]))
        if not account or int(data.get("sv", -1)) != account.session_version:
            return None
        return account
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None
    finally:
        db.close()

def school_chat_user_ids(db: Session, school_id: int) -> set[int]:
    member_ids = set(
        db.scalars(
            select(UserSchool.user_id).where(UserSchool.school_id == school_id)
        ).all()
    )
    member_ids.update(
        db.scalars(select(User.id).where(User.role == "super_admin")).all()
    )
    return member_ids

def presence_visible_user_ids(db: Session, viewer: User) -> set[int]:
    """Users whose online state may be exposed to this viewer."""
    if is_super_admin(viewer):
        return set(db.scalars(select(User.id)).all())

    visible = {viewer.id}
    for school_id in user_school_ids(viewer, db):
        visible.update(school_chat_user_ids(db, school_id))
    # Super admins may manage school-less accounts, but ordinary users must not
    # receive presence information from unrelated schools.
    visible.update(db.scalars(select(User.id).where(User.role == "super_admin")).all())
    return visible

def presence_recipients_for_user(db: Session, subject: User) -> set[int]:
    """Users allowed to receive a generic presence event for subject."""
    if is_super_admin(subject):
        return set(db.scalars(select(User.id)).all())

    recipients = set(
        db.scalars(select(User.id).where(User.role == "super_admin")).all()
    )
    for school_id in user_school_ids(subject, db):
        recipients.update(school_chat_user_ids(db, school_id))
    recipients.add(subject.id)
    return recipients

async def broadcast_school_presence(user: User, online: bool, last_seen: str) -> None:
    db = SessionLocal()
    try:
        school_ids = user_school_ids(user, db)
        for school_id in school_ids:
            recipients = school_chat_user_ids(db, school_id)
            await realtime_manager.broadcast(
                {
                    "type": "school_presence",
                    "school_id": school_id,
                    "user_id": user.id,
                    "online": online,
                    "last_seen": last_seen,
                    "online_count": realtime_manager.online_count_for(recipients),
                },
                only_user_ids=recipients,
            )
    finally:
        db.close()

async def _broadcast_delayed_offline(user_id: int, last_seen: str) -> None:
    # Avoid Online -> Offline -> Online flicker when the browser simply reloads.
    await asyncio.sleep(4)
    if realtime_manager.is_online(user_id):
        return
    db = SessionLocal()
    try:
        account = db.get(User, user_id)
        if not account:
            return
        recipients = presence_recipients_for_user(db, account)
        await realtime_manager.broadcast(
            {
                "type": "presence",
                "user_id": user_id,
                "online": False,
                "last_seen": last_seen,
                "online_count": realtime_manager.online_count_for(recipients),
            },
            only_user_ids=recipients,
        )
        await broadcast_school_presence(account, False, last_seen)
    finally:
        db.close()

def _payload_school_id(payload: dict) -> int | None:
    try:
        value = payload.get("school_id")
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


__all__ = [name for name in globals() if not name.startswith('__')]
