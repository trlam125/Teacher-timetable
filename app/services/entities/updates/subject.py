from __future__ import annotations

from app.subject_catalog import subject_key
from app.models import Project, Subject
from app.services.entities.validation import ensure_unique_project_name
from app.services.web import bounded_text
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session


def update_subject_fields(db: Session, project: Project, obj, d: dict, name: str, pid: int):
    # Use catalog aliases to reject duplicates, while preserving editable labels.
    others = db.scalars(select(Subject).where(Subject.project_id == pid, Subject.id != obj.id)).all()
    if any(subject_key(existing.name) == subject_key(name) for existing in others):
        raise HTTPException(409, f"Môn {name} đã tồn tại dưới tên khác. Hãy xử lý môn trùng trước khi đổi.")
    ensure_unique_project_name(db, Subject, pid, name, "Môn học", exclude_id=obj.id)
    obj.name = name
    obj.short_name = bounded_text(d.get("short_name", ""), "Tên rút gọn", 20)
    return 0, [], 0, []
