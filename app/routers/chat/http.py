from __future__ import annotations

from fastapi import APIRouter
from app.services.runtime import *

router = APIRouter()


@router.get("/api/chat/schools")
def chat_schools(
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    schools = user_schools(user, db)
    return {
        "schools": [{"id": school.id, "name": school.name} for school in schools],
        "default_school_id": schools[0].id if schools else None,
    }


@router.get("/api/chat/general/messages")
def general_chat_messages(
    school_id: int,
    limit: int = 50,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    school = db.get(School, school_id)
    if not school or not user_can_access_school(user, school_id, db):
        raise HTTPException(403, "Bạn không có quyền truy cập chat của trường này")

    safe_limit = max(1, min(int(limit or 50), 100))
    rows = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.school_id == school_id)
        .order_by(ChatMessage.id.desc())
        .limit(safe_limit)
    ).all()
    ordered_rows = list(reversed(rows))
    reply_ids = {
        int(row.reply_to_id) for row in ordered_rows if row.reply_to_id is not None
    }
    reply_rows = {}
    if reply_ids:
        reply_rows = {
            row.id: row
            for row in db.scalars(
                select(ChatMessage).where(
                    ChatMessage.id.in_(reply_ids),
                    ChatMessage.school_id == school_id,
                )
            ).all()
        }

    def reply_preview(row: ChatMessage) -> dict | None:
        if row.reply_to_id is None:
            return None
        target = reply_rows.get(int(row.reply_to_id))
        if target is None:
            return {
                "id": int(row.reply_to_id),
                "user_name": "Tin nhắn không còn tồn tại",
                "content": "Tin nhắn không còn tồn tại",
                "deleted": True,
            }
        deleted = bool(target.deleted_at)
        return {
            "id": target.id,
            "user_name": target.user_name or "Tài khoản đã xóa",
            "content": "Tin nhắn đã bị xóa" if deleted else target.content,
            "deleted": deleted,
        }

    messages = [
        {
            "id": row.id,
            "school_id": row.school_id,
            "user_id": row.user_id,
            "user_name": row.user_name or "Tài khoản đã xóa",
            "content": "Tin nhắn đã bị xóa" if row.deleted_at else row.content,
            "created_at": row.created_at,
            "edited_at": row.edited_at,
            "deleted_at": row.deleted_at,
            "reply_to_id": row.reply_to_id,
            "reply": reply_preview(row),
        }
        for row in ordered_rows
    ]
    return {"school": {"id": school.id, "name": school.name}, "messages": messages}
