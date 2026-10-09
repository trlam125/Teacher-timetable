from __future__ import annotations

from app.models import Department, Grade, SchoolClass, Subject, Teacher, User
from app.services.authentication.sessions import current_user, db_session
from app.services.entities.deletion import schedule_displacement_confirmation
from app.services.entities.schemas import EntityIn
from app.services.entities.updates.department import update_department_fields
from app.services.entities.updates.grade import update_grade_fields
from app.services.entities.updates.school_class import update_class_fields
from app.services.entities.updates.subject import update_subject_fields
from app.services.entities.updates.teacher import update_teacher_fields
from app.services.projects import get_project_for_update
from app.services.web import bounded_text
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session


router = APIRouter()


@router.put("/api/projects/{pid}/entity/{typ}/{eid}")
def update_entity(
    pid: int,
    typ: str,
    eid: int,
    payload: EntityIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    if payload.type != typ or typ not in {
        "department",
        "subject",
        "teacher",
        "grade",
        "class",
    }:
        raise HTTPException(400, "Loại dữ liệu không hợp lệ")
    model = {
        "department": Department,
        "subject": Subject,
        "teacher": Teacher,
        "grade": Grade,
        "class": SchoolClass,
    }[typ]
    obj = db.get(model, eid)
    if not obj or obj.project_id != pid:
        raise HTTPException(404, "Không tìm thấy dữ liệu cần sửa")
    d = payload.data
    name_limit = {
        "department": 120,
        "subject": 120,
        "teacher": 120,
        "grade": 80,
        "class": 80,
    }[typ]
    name = bounded_text(d.get("name", ""), "Tên", name_limit)
    handler = {
        "department": update_department_fields,
        "subject": update_subject_fields,
        "teacher": update_teacher_fields,
        "grade": update_grade_fields,
        "class": update_class_fields,
    }[typ]
    result = handler(db, project, obj, d, name, pid)
    if isinstance(result, JSONResponse):
        return result
    synced_assignments, displaced_lesson_ids, removed_extra_assignments, missing_grade_assignments = result
    confirmation = schedule_displacement_confirmation(
        db,
        displaced_lesson_ids,
        confirmed=d.get("confirm_displacement") is True,
        confirmed_ids=d.get("confirmed_displaced_lesson_ids"),
    )
    if confirmation is not None:
        return confirmation
    db.commit()
    return {
        "ok": True,
        "displaced_lessons": len(set(displaced_lesson_ids)),
        "synced_assignments": synced_assignments,
        "removed_extra_assignments": removed_extra_assignments,
        "missing_grade_assignments": missing_grade_assignments,
        "missing_grade_assignments_count": len(missing_grade_assignments),
    }
