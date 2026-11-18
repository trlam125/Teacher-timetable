from __future__ import annotations

import asyncio
import json
import secrets
import time

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from app.services.authentication.csrf import require_same_origin

from app.logging_config import logger
from app.services.realtime.events import connection_context, handle_event, school_presence_context
from app.services.realtime.manager import ConnectionLimitExceeded, realtime_manager
from app.services.realtime.presence import _broadcast_delayed_offline, broadcast_school_presence
from app.services.realtime.utils import touch_user_last_seen, websocket_session_user
from app.services.traffic import TokenBuckets
from app.settings import WS_EVENTS_PER_MINUTE, WS_EVENT_BURST

router = APIRouter()
# Shared between this worker's sockets: reconnecting does not reset the user budget.
_event_budget = TokenBuckets(rate=WS_EVENTS_PER_MINUTE / 60, burst=WS_EVENT_BURST)


async def _send(websocket, payload):
    await asyncio.wait_for(websocket.send_json(payload), realtime_manager.SEND_TIMEOUT_SECONDS)


async def _register(account, connection_id, websocket):
    task = asyncio.create_task(asyncio.to_thread(
        realtime_manager.add, account.id, connection_id, websocket
    ))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # A cancelled await cannot stop a database thread. Finish it before cleanup.
        try:
            await task
        finally:
            realtime_manager.discard_local(account.id, connection_id)
            await asyncio.to_thread(realtime_manager.remove, account.id, connection_id)
        raise


@router.websocket("/ws/realtime")
async def realtime_socket(websocket: WebSocket):
    try:
        require_same_origin(websocket, allow_missing=False)
    except HTTPException:
        await websocket.close(code=1008)
        return
    account = await asyncio.to_thread(websocket_session_user, websocket)
    if account is None:
        await websocket.close(code=4401)
        return
    connection_id = secrets.token_urlsafe(12)
    registered = False
    try:
        await websocket.accept()
        # Capture the event loop here; all synchronous persistence runs in a worker.
        realtime_manager._ensure_listener(asyncio.get_running_loop())
        try:
            first_connection = await _register(account, connection_id, websocket)
        except ConnectionLimitExceeded:
            await websocket.close(code=1013)
            return
        registered = True
        last_seen, visible, recipients = await asyncio.to_thread(connection_context, account)
        online = await asyncio.to_thread(realtime_manager.online_user_ids_for, visible)
        await _send(websocket, {"type": "ready", "user_id": account.id,
                                "user_name": account.name, "online_user_ids": online,
                                "online_count": len(online)})
        if first_connection:
            online = await asyncio.to_thread(realtime_manager.online_user_ids_for, recipients)
            await realtime_manager.broadcast(
                {"type": "presence", "user_id": account.id, "online": True,
                 "last_seen": last_seen, "online_count": len(online)}, only_user_ids=recipients,
            )
            await broadcast_school_presence(account, True, last_seen)
        checked = time.monotonic()
        while True:
            timed_out = False
            try:
                payload = await asyncio.wait_for(
                    websocket.receive_json(), realtime_manager.SESSION_CHECK_INTERVAL_SECONDS
                )
            except asyncio.TimeoutError:
                timed_out = True
                payload = None
            if not timed_out and not _event_budget.allow(str(account.id)):
                await websocket.close(code=1008)
                break
            if timed_out or time.monotonic() - checked >= realtime_manager.SESSION_CHECK_INTERVAL_SECONDS:
                refreshed = await asyncio.to_thread(websocket_session_user, websocket)
                if refreshed is None:
                    await websocket.close(code=4401)
                    break
                account, checked = refreshed, time.monotonic()
                # Keep the shared connection lease alive even for idle clients.
                await asyncio.to_thread(realtime_manager.touch, account.id, connection_id)
            if timed_out:
                continue
            if not isinstance(payload, dict):
                continue
            actions = await asyncio.to_thread(
                handle_event, account.id, account.session_version, payload, connection_id, dict(websocket.cookies)
            )
            closing = False
            for action in actions:
                if action[0] == "send":
                    await _send(websocket, action[1])
                elif action[0] == "close":
                    await websocket.close(code=action[1])
                    closing = True
                    break
                else:
                    await realtime_manager.broadcast(
                        action[1], only_user_ids=action[2], exclude_user_id=action[3]
                    )
            if closing:
                break
    except WebSocketDisconnect:
        pass
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        await websocket.close(code=1007)
    except Exception:
        logger.exception("Realtime WebSocket error for user_id=%s", account.id)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        if registered:
            realtime_manager.discard_local(account.id, connection_id)
            try:
                became_offline = await asyncio.to_thread(realtime_manager.remove, account.id, connection_id)
                schools = await asyncio.to_thread(school_presence_context, account)
                for school_id, recipients in schools:
                    await realtime_manager.broadcast(
                        {"type": "typing", "school_id": school_id, "user_id": account.id,
                         "user_name": account.name, "typing": False},
                        exclude_user_id=account.id, only_user_ids=recipients,
                    )
                if became_offline:
                    last_seen = await asyncio.to_thread(touch_user_last_seen, account.id)
                    asyncio.create_task(_broadcast_delayed_offline(account.id, last_seen))
            except Exception:
                logger.exception("Realtime cleanup failed for user_id=%s", account.id)
