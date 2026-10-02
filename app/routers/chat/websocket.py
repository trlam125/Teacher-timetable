from __future__ import annotations

from fastapi import APIRouter
from app.services.runtime import *

router = APIRouter()


def _client_message_id(payload: dict) -> str | None:
    value = str(payload.get("client_id") or "").strip()
    if not value or len(value) > 80:
        return None
    return value


async def _send_chat_error(
    websocket: WebSocket,
    message: str,
    *,
    client_id: str | None = None,
) -> None:
    payload = {"type": "chat_error", "message": message}
    if client_id:
        payload["client_id"] = client_id
    await websocket.send_json(payload)


@router.websocket("/ws/realtime")
async def realtime_socket(websocket: WebSocket):
    account = await asyncio.to_thread(websocket_session_user, websocket)
    if account is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    connection_id = secrets.token_urlsafe(12)
    # Register on the event-loop thread so the PostgreSQL listener captures
    # the correct loop; registration itself only happens once per socket.
    first_connection = realtime_manager.add(account.id, connection_id, websocket)
    last_seen = touch_user_last_seen(account.id)
    last_session_check_at = time.monotonic()

    db = SessionLocal()
    try:
        visible_user_ids = presence_visible_user_ids(db, account)
        presence_recipients = presence_recipients_for_user(db, account)
    finally:
        db.close()

    visible_online_ids = await asyncio.to_thread(
        realtime_manager.online_user_ids_for, visible_user_ids
    )
    await websocket.send_json(
        {
            "type": "ready",
            "user_id": account.id,
            "user_name": account.name,
            "online_user_ids": visible_online_ids,
            "online_count": len(visible_online_ids),
        }
    )
    if first_connection:
        presence_online_ids = await asyncio.to_thread(
            realtime_manager.online_user_ids_for, presence_recipients
        )
        await realtime_manager.broadcast(
            {
                "type": "presence",
                "user_id": account.id,
                "online": True,
                "last_seen": last_seen,
                "online_count": len(presence_online_ids),
            },
            only_user_ids=presence_recipients,
        )
        await broadcast_school_presence(account, True, last_seen)

    try:
        while True:
            # Idle sockets still expire on a short interval. Active events are
            # validated once below with the same DB row used by the event.
            try:
                payload = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=realtime_manager.SESSION_CHECK_INTERVAL_SECONDS,
                )
            except asyncio.TimeoutError:
                # Idle sockets still expire/revoke promptly, but an active event
                # no longer performs this query and then immediately queries the
                # same user a second time below.
                refreshed = await asyncio.to_thread(websocket_session_user, websocket)
                if refreshed is None:
                    await websocket.close(code=4401)
                    break
                account = refreshed
                last_session_check_at = time.monotonic()
                continue

            if not isinstance(payload, dict):
                continue

            # Active clients must not keep an expired cookie alive forever. Do
            # the full signed-cookie check at most once per interval; ordinary
            # events still need only the single account query below.
            if (
                time.monotonic() - last_session_check_at
                >= realtime_manager.SESSION_CHECK_INTERVAL_SECONDS
            ):
                refreshed = await asyncio.to_thread(websocket_session_user, websocket)
                if refreshed is None:
                    await websocket.close(code=4401)
                    break
                account = refreshed
                last_session_check_at = time.monotonic()

            event_type = str(payload.get("type") or "").strip()

            db = SessionLocal()
            try:
                current = db.get(User, account.id)
                if not current or current.session_version != account.session_version:
                    await websocket.close(code=4401)
                    break
                account = current

                if event_type == "activity":
                    touch_user_last_seen(current.id, min_interval_seconds=45)
                    await asyncio.to_thread(
                        realtime_manager.touch, current.id, connection_id
                    )
                    visible_user_ids = presence_visible_user_ids(db, current)
                    online_user_ids = await asyncio.to_thread(
                        realtime_manager.online_user_ids_for, visible_user_ids
                    )
                    await websocket.send_json(
                        {
                            "type": "presence_sync",
                            "online_user_ids": online_user_ids,
                            "online_count": len(online_user_ids),
                        }
                    )
                    continue

                if event_type == "room_join":
                    school_id = _payload_school_id(payload)
                    school = (
                        db.get(School, school_id) if school_id is not None else None
                    )
                    if not school or not user_can_access_school(current, school_id, db):
                        await websocket.send_json(
                            {
                                "type": "chat_error",
                                "message": "Bạn không có quyền truy cập trường này.",
                            }
                        )
                        continue
                    recipients = school_chat_user_ids(db, school_id)
                    room_online_ids = await asyncio.to_thread(
                        realtime_manager.online_user_ids_for, recipients
                    )
                    await websocket.send_json(
                        {
                            "type": "room_ready",
                            "school_id": school.id,
                            "school_name": school.name,
                            "online_user_ids": room_online_ids,
                            "online_count": len(room_online_ids),
                        }
                    )
                    continue

                if event_type == "typing":
                    school_id = _payload_school_id(payload)
                    if school_id is None or not user_can_access_school(
                        current, school_id, db
                    ):
                        continue
                    recipients = school_chat_user_ids(db, school_id)
                    await realtime_manager.broadcast(
                        {
                            "type": "typing",
                            "school_id": school_id,
                            "user_id": current.id,
                            "user_name": current.name,
                            "typing": bool(payload.get("typing")),
                        },
                        exclude_user_id=current.id,
                        only_user_ids=recipients,
                    )
                    continue

                if event_type not in {"chat_send", "chat_edit", "chat_delete"}:
                    continue

                if event_type == "chat_send":
                    client_id = _client_message_id(payload)
                    school_id = _payload_school_id(payload)
                    school = (
                        db.get(School, school_id) if school_id is not None else None
                    )
                    if not school or not user_can_access_school(current, school_id, db):
                        await _send_chat_error(
                            websocket,
                            "Bạn không có quyền gửi tin nhắn vào trường này.",
                            client_id=client_id,
                        )
                        continue
                    content = str(payload.get("content") or "").strip()
                    if not content:
                        await _send_chat_error(
                            websocket,
                            "Tin nhắn không được để trống.",
                            client_id=client_id,
                        )
                        continue
                    if len(content) > 2000:
                        await _send_chat_error(
                            websocket,
                            "Tin nhắn tối đa 2000 ký tự.",
                            client_id=client_id,
                        )
                        continue

                    reply_to_id = payload.get("reply_to_id")
                    try:
                        reply_to_id = (
                            int(reply_to_id) if reply_to_id is not None else None
                        )
                    except (TypeError, ValueError):
                        reply_to_id = None
                    reply_target = None
                    if reply_to_id is not None:
                        reply_target = db.get(ChatMessage, reply_to_id)
                        if reply_target is None or reply_target.school_id != school_id:
                            await _send_chat_error(
                                websocket,
                                "Tin nhắn được trả lời không còn tồn tại trong trường này.",
                                client_id=client_id,
                            )
                            continue

                    created_at = _utc_now_iso()
                    row = ChatMessage(
                        school_id=school_id,
                        user_id=current.id,
                        user_name=current.name,
                        user_email=current.email,
                        content=content,
                        reply_to_id=reply_to_id,
                        created_at=created_at,
                    )
                    current.last_seen = created_at
                    db.add(row)
                    db.commit()
                    reply_payload = None
                    if reply_target is not None:
                        reply_deleted = bool(reply_target.deleted_at)
                        reply_payload = {
                            "id": reply_target.id,
                            "user_name": reply_target.user_name or "Tài khoản đã xóa",
                            "content": "Tin nhắn đã bị xóa"
                            if reply_deleted
                            else reply_target.content,
                            "deleted": reply_deleted,
                        }
                    recipients = school_chat_user_ids(db, school_id)
                    await realtime_manager.broadcast(
                        {
                            "type": "chat_message",
                            "school_id": school_id,
                            "client_id": client_id,
                            "message": {
                                "id": row.id,
                                "school_id": school_id,
                                "user_id": current.id,
                                "user_name": current.name,
                                "content": row.content,
                                "created_at": row.created_at,
                                "edited_at": row.edited_at,
                                "deleted_at": row.deleted_at,
                                "reply_to_id": row.reply_to_id,
                                "reply": reply_payload,
                            },
                        },
                        only_user_ids=recipients,
                    )
                    continue

                message_id = payload.get("message_id")
                try:
                    message_id = int(message_id)
                except (TypeError, ValueError):
                    await websocket.send_json(
                        {"type": "chat_error", "message": "Tin nhắn không hợp lệ."}
                    )
                    continue

                row = db.get(ChatMessage, message_id)
                if row is None or row.school_id is None:
                    await websocket.send_json(
                        {"type": "chat_error", "message": "Tin nhắn không còn tồn tại."}
                    )
                    continue
                if not user_can_access_school(current, row.school_id, db):
                    await websocket.send_json(
                        {
                            "type": "chat_error",
                            "message": "Bạn không có quyền thao tác tin nhắn này.",
                        }
                    )
                    continue

                recipients = school_chat_user_ids(db, row.school_id)
                if event_type == "chat_edit":
                    if row.deleted_at:
                        await websocket.send_json(
                            {"type": "chat_error", "message": "Tin nhắn đã bị xóa."}
                        )
                        continue
                    if row.user_id != current.id:
                        await websocket.send_json(
                            {
                                "type": "chat_error",
                                "message": "Bạn chỉ có thể sửa tin nhắn của mình.",
                            }
                        )
                        continue
                    content = str(payload.get("content") or "").strip()
                    if not content:
                        await websocket.send_json(
                            {
                                "type": "chat_error",
                                "message": "Tin nhắn không được để trống.",
                            }
                        )
                        continue
                    if len(content) > 2000:
                        await websocket.send_json(
                            {
                                "type": "chat_error",
                                "message": "Tin nhắn tối đa 2000 ký tự.",
                            }
                        )
                        continue
                    edited_at = _utc_now_iso()
                    row.content = content
                    row.edited_at = edited_at
                    current.last_seen = edited_at
                    db.commit()
                    await realtime_manager.broadcast(
                        {
                            "type": "chat_message_updated",
                            "school_id": row.school_id,
                            "message": {
                                "id": row.id,
                                "content": row.content,
                                "edited_at": row.edited_at,
                            },
                        },
                        only_user_ids=recipients,
                    )
                    continue

                can_delete = row.user_id == current.id or current.role == "super_admin"
                if not can_delete:
                    await websocket.send_json(
                        {
                            "type": "chat_error",
                            "message": "Bạn không có quyền xóa tin nhắn này.",
                        }
                    )
                    continue
                if row.deleted_at:
                    continue
                deleted_at = _utc_now_iso()
                row.content = ""
                row.deleted_at = deleted_at
                current.last_seen = deleted_at
                db.commit()
                await realtime_manager.broadcast(
                    {
                        "type": "chat_message_deleted",
                        "school_id": row.school_id,
                        "message_id": row.id,
                        "deleted_at": row.deleted_at,
                    },
                    only_user_ids=recipients,
                )
            finally:
                db.close()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Realtime WebSocket error for user_id=%s", account.id)
    finally:
        # Remove this socket before broadcasting cleanup events, so a revoked
        # connection is not selected again while its close handler is running.
        became_offline = await asyncio.to_thread(
            realtime_manager.remove, account.id, connection_id
        )
        # Clear typing state in every school the account can access.
        db = SessionLocal()
        try:
            for school_id in user_school_ids(account, db):
                recipients = school_chat_user_ids(db, school_id)
                await realtime_manager.broadcast(
                    {
                        "type": "typing",
                        "school_id": school_id,
                        "user_id": account.id,
                        "user_name": account.name,
                        "typing": False,
                    },
                    exclude_user_id=account.id,
                    only_user_ids=recipients,
                )
        finally:
            db.close()
        if became_offline:
            last_seen = touch_user_last_seen(account.id)
            asyncio.create_task(_broadcast_delayed_offline(account.id, last_seen))
