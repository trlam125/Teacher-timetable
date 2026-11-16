"""Synchronous chat transactions. Call from worker threads, never the event loop."""
from __future__ import annotations

from app.database import SessionLocal
from app.models import ChatMessage, School, User
from app.services.authentication.permissions import user_can_access_school, user_school_ids
from .manager import realtime_manager
from .utils import (
    _payload_school_id, _utc_now_iso, presence_recipients_for_user,
    presence_visible_user_ids, school_chat_user_ids, touch_user_last_seen,
)


def connection_context(account):
    last_seen = touch_user_last_seen(account.id)
    with SessionLocal() as db:
        visible = presence_visible_user_ids(db, account)
        recipients = presence_recipients_for_user(db, account)
    return last_seen, visible, recipients


def school_presence_context(account):
    with SessionLocal() as db:
        return [(sid, school_chat_user_ids(db, sid)) for sid in user_school_ids(account, db)]


def offline_context(user_id):
    with SessionLocal() as db:
        account = db.get(User, user_id)
        if account is None:
            return None
        return account, presence_recipients_for_user(db, account)


def handle_event(user_id, session_version, payload, connection_id):
    """Return transport actions containing detached values, after closing the session."""
    event = str(payload.get("type") or "").strip()
    if event not in {"activity", "room_join", "typing", "chat_send", "chat_edit", "chat_delete"}:
        return []
    client_id = str(payload.get("client_id") or "").strip()
    client_id = client_id if 0 < len(client_id) <= 80 else None

    def error(message):
        data = {"type": "chat_error", "message": message}
        if event == "chat_send" and client_id:
            data["client_id"] = client_id
        return [("send", data)]

    with SessionLocal() as db:
        current = db.get(User, user_id)
        if current is None or current.session_version != session_version:
            return [("close", 4401)]
        if event == "activity":
            # This function runs in a worker, including these persistence helpers.
            visible = presence_visible_user_ids(db, current)
            db.close()
            touch_user_last_seen(user_id, min_interval_seconds=45)
            realtime_manager.touch(user_id, connection_id)
            online = realtime_manager.online_user_ids_for(visible)
            return [("send", {"type": "presence_sync", "online_user_ids": online,
                              "online_count": len(online)})]

        if event in {"room_join", "typing", "chat_send"}:
            school_id = _payload_school_id(payload)
            school = db.get(School, school_id) if school_id is not None else None
            if school is None or not user_can_access_school(current, school_id, db):
                return [] if event == "typing" else error("Bạn không có quyền truy cập trường này.")
            recipients = school_chat_user_ids(db, school_id)
            if event == "room_join":
                school_name = school.name
                db.close()
                online = realtime_manager.online_user_ids_for(recipients)
                return [("send", {"type": "room_ready", "school_id": school_id,
                                  "school_name": school_name, "online_user_ids": online,
                                  "online_count": len(online)})]
            if event == "typing":
                return [("broadcast", {"type": "typing", "school_id": school_id,
                                       "user_id": current.id, "user_name": current.name,
                                       "typing": bool(payload.get("typing"))}, recipients, user_id)]
            content = str(payload.get("content") or "").strip()
            if not content:
                return error("Tin nhắn không được để trống.")
            if len(content) > 2000:
                return error("Tin nhắn tối đa 2000 ký tự.")
            try:
                reply_id = int(payload["reply_to_id"]) if payload.get("reply_to_id") is not None else None
            except (TypeError, ValueError):
                reply_id = None
            reply = db.get(ChatMessage, reply_id) if reply_id is not None else None
            if reply_id is not None and (reply is None or reply.school_id != school_id):
                return error("Tin nhắn được trả lời không còn tồn tại trong trường này.")
            created = _utc_now_iso()
            row = ChatMessage(school_id=school_id, user_id=current.id, user_name=current.name,
                              user_email=current.email, content=content, reply_to_id=reply_id,
                              created_at=created)
            current.last_seen = created
            db.add(row)
            db.commit()
            reply_data = None if reply is None else {
                "id": reply.id, "user_name": reply.user_name or "Tài khoản đã xóa",
                "content": "Tin nhắn đã bị xóa" if reply.deleted_at else reply.content,
                "deleted": bool(reply.deleted_at),
            }
            return [("broadcast", {"type": "chat_message", "school_id": school_id,
                                   "client_id": client_id, "message": {
                                       "id": row.id, "school_id": school_id,
                                       "user_id": current.id, "user_name": current.name,
                                       "content": row.content, "created_at": row.created_at,
                                       "edited_at": row.edited_at, "deleted_at": row.deleted_at,
                                       "reply_to_id": row.reply_to_id, "reply": reply_data,
                                   }}, recipients, None)]

        try:
            message_id = int(payload.get("message_id"))
        except (TypeError, ValueError):
            return error("Tin nhắn không hợp lệ.")
        row = db.get(ChatMessage, message_id)
        if row is None or row.school_id is None:
            return error("Tin nhắn không còn tồn tại.")
        if not user_can_access_school(current, row.school_id, db):
            return error("Bạn không có quyền thao tác tin nhắn này.")
        recipients = school_chat_user_ids(db, row.school_id)
        if event == "chat_edit":
            if row.deleted_at:
                return error("Tin nhắn đã bị xóa.")
            if row.user_id != current.id:
                return error("Bạn chỉ có thể sửa tin nhắn của mình.")
            content = str(payload.get("content") or "").strip()
            if not content:
                return error("Tin nhắn không được để trống.")
            if len(content) > 2000:
                return error("Tin nhắn tối đa 2000 ký tự.")
            row.content, row.edited_at = content, _utc_now_iso()
            current.last_seen = row.edited_at
            db.commit()
            data = {"type": "chat_message_updated", "school_id": row.school_id,
                    "message": {"id": row.id, "content": row.content, "edited_at": row.edited_at}}
        else:
            if row.user_id != current.id and current.role != "super_admin":
                return error("Bạn không có quyền xóa tin nhắn này.")
            if row.deleted_at:
                return []
            row.content, row.deleted_at = "", _utc_now_iso()
            current.last_seen = row.deleted_at
            db.commit()
            data = {"type": "chat_message_deleted", "school_id": row.school_id,
                    "message_id": row.id, "deleted_at": row.deleted_at}
        return [("broadcast", data, recipients, None)]
