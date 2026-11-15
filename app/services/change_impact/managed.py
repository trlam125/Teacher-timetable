from fastapi import HTTPException

from app.models import ProjectChangeSettings


def post_schedule_editing_enabled(db, project_id):
    settings = db.get(ProjectChangeSettings, project_id)
    return settings is not None and settings.post_schedule_editing


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
