from __future__ import annotations

from app.models import Assignment, Project, Subject
from app.services.entities.validation import (
    ensure_unique_teacher_short_name,
    replace_teacher_subjects,
    validated_subject_ids,
)
from app.services.web import bounded_text
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session


def update_teacher_fields(db: Session, project: Project, obj, d: dict, name: str, pid: int):
    short_name = bounded_text(d.get("short_name", ""), "Tên ngắn", 30)
    ensure_unique_teacher_short_name(db, pid, short_name, exclude_id=obj.id)
    if "subject_ids" in d:
        subject_ids = validated_subject_ids(db, pid, d.get("subject_ids"))
        assigned_subject_ids = set(db.scalars(
            select(Assignment.subject_id).where(
                Assignment.project_id == pid, Assignment.teacher_id == obj.id,
            )
        ).all())
        removed_in_use = assigned_subject_ids - set(subject_ids)
        if removed_in_use:
            names = db.scalars(select(Subject.name).where(Subject.id.in_(removed_in_use))).all()
            raise HTTPException(
                409, "Không thể bỏ môn đang có phân công: " + ", ".join(names)
                + ". Hãy xóa/chuyển phân công trước.",
            )
        replace_teacher_subjects(db, pid, obj.id, subject_ids)
    obj.name = name
    obj.short_name = short_name
    return 0, [], 0, []
