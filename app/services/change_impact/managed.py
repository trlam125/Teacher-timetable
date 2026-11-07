from fastapi import HTTPException


def managed_edit(db):
    return db.info.get("project_change_managed") is True


def finish_edit(db):
    if managed_edit(db):
        db.flush()
    else:
        db.commit()


def require_preview(db):
    if not managed_edit(db):
        raise HTTPException(409, {
            "reason": "impact_preview_required",
            "message": "Hãy xem trước ảnh hưởng và xác nhận thay đổi trước khi lưu.",
        })
