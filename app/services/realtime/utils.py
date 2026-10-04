from __future__ import annotations

from app.services.foundation import *
from app.services.web import *
from app.services.auth import *


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
            if (
                previous is not None
                and (now - previous).total_seconds() < min_interval_seconds
            ):
                return account.last_seen or now_iso
        account.last_seen = now_iso
        db.commit()
        return now_iso
    finally:
        db.close()


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
    """Return school members and super admins with one database round-trip."""
    member_ids = select(UserSchool.user_id).where(UserSchool.school_id == school_id)
    super_admin_ids = select(User.id).where(User.role == "super_admin")
    return set(db.scalars(member_ids.union(super_admin_ids)).all())


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


def _payload_school_id(payload: dict) -> int | None:
    try:
        value = payload.get("school_id")
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


__all__ = [name for name in globals() if not name.startswith("__")]
