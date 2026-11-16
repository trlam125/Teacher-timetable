from __future__ import annotations

import asyncio

from .manager import realtime_manager
from .events import offline_context, school_presence_context
from app.models import User


async def broadcast_school_presence(user: User, online: bool, last_seen: str) -> None:
    schools = await asyncio.to_thread(school_presence_context, user)
    for school_id, recipients in schools:
        online_ids = await asyncio.to_thread(realtime_manager.online_user_ids_for, recipients)
        await realtime_manager.broadcast(
            {"type": "school_presence", "school_id": school_id, "user_id": user.id,
             "online": online, "last_seen": last_seen, "online_count": len(online_ids)},
            only_user_ids=recipients,
        )


async def _broadcast_delayed_offline(user_id: int, last_seen: str) -> None:
    # Avoid Online -> Offline -> Online flicker when the browser simply reloads.
    await asyncio.sleep(4)
    if await asyncio.to_thread(realtime_manager.is_online, user_id):
        return
    context = await asyncio.to_thread(offline_context, user_id)
    if context is None:
        return
    account, recipients = context
    online_ids = await asyncio.to_thread(realtime_manager.online_user_ids_for, recipients)
    await realtime_manager.broadcast(
        {"type": "presence", "user_id": user_id, "online": False,
         "last_seen": last_seen, "online_count": len(online_ids)},
        only_user_ids=recipients,
    )
    await broadcast_school_presence(account, False, last_seen)


__all__ = [name for name in globals() if not name.startswith("__")]
