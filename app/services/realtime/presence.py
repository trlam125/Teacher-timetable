from __future__ import annotations

from app.services.foundation import *
from app.services.web import *
from app.services.auth import *
from .manager import realtime_manager
from .utils import *


async def broadcast_school_presence(user: User, online: bool, last_seen: str) -> None:
    db = SessionLocal()
    try:
        school_ids = user_school_ids(user, db)
        for school_id in school_ids:
            recipients = school_chat_user_ids(db, school_id)
            online_ids = await asyncio.to_thread(
                realtime_manager.online_user_ids_for, recipients
            )
            await realtime_manager.broadcast(
                {
                    "type": "school_presence",
                    "school_id": school_id,
                    "user_id": user.id,
                    "online": online,
                    "last_seen": last_seen,
                    "online_count": len(online_ids),
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
        online_ids = await asyncio.to_thread(
            realtime_manager.online_user_ids_for, recipients
        )
        await realtime_manager.broadcast(
            {
                "type": "presence",
                "user_id": user_id,
                "online": False,
                "last_seen": last_seen,
                "online_count": len(online_ids),
            },
            only_user_ids=recipients,
        )
        await broadcast_school_presence(account, False, last_seen)
    finally:
        db.close()


__all__ = [name for name in globals() if not name.startswith("__")]
