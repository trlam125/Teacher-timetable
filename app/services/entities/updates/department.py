from __future__ import annotations

from app.models import Department, Project
from app.services.entities.validation import ensure_unique_project_name
from sqlalchemy.orm import Session


def update_department_fields(db: Session, project: Project, obj, d: dict, name: str, pid: int):
    synced_assignments = 0
    displaced_lesson_ids: list[int] = []
    removed_extra_assignments = 0
    missing_grade_assignments: list[str] = []
    ensure_unique_project_name(
        db, Department, pid, name, "Tổ chuyên môn", exclude_id=obj.id
    )
    obj.name = name
    return synced_assignments, displaced_lesson_ids, removed_extra_assignments, missing_grade_assignments
