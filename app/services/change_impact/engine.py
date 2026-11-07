from __future__ import annotations

import json

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.models import Assignment, Department, Grade, Lesson, SchoolClass, Subject, Teacher
from app.services.change_impact.assignments import edit_assignment
from app.services.change_impact.reconcile import protect_assignment
from app.services.change_impact.state import capture, schedule_unchanged
from app.services.entities.deletion import delete_entity_related_rows, entity_delete_dependency
from app.services.entities.updates.department import update_department_fields
from app.services.entities.updates.grade import update_grade_fields
from app.services.entities.updates.school_class import update_class_fields
from app.services.entities.updates.subject import update_subject_fields
from app.services.entities.updates.teacher import update_teacher_fields
from app.services.edit_conflicts import current_edit_token, edit_token, require_current_edit
from app.services.web import bounded_text
from app.services.entities.validation import validated_subject_ids
from app.services.schedule_operations.validation import schedule_integrity_report

MODELS = {"assignment": Assignment, "department": Department, "grade": Grade,
          "class": SchoolClass, "subject": Subject, "teacher": Teacher}
HANDLERS = {"department": update_department_fields, "grade": update_grade_fields,
            "class": update_class_fields, "subject": update_subject_fields, "teacher": update_teacher_fields}


def target(db, project, typ, eid):
    model = MODELS.get(typ)
    obj = db.get(model, eid) if model else None
    if not obj or obj.project_id != project.id:
        raise HTTPException(404, "Không tìm thấy dữ liệu trong project này.")
    return obj


def resolve_assignments(db, project, assignments, resolutions, *, allow_transfer):
    unresolved = [row for row in assignments if str(row.id) not in resolutions]
    if unresolved:
        raise HTTPException(409, {
            "reason": "assignment_resolution_required",
            "message": "Chọn cách xử lý từng phân công liên quan trước khi tiếp tục.",
            "assignments": [
                {"id": row.id, "class_name": db.get(SchoolClass, row.class_id).name,
                 "subject_name": db.get(Subject, row.subject_id).name,
                 "teacher_id": row.teacher_id, "subject_id": row.subject_id,
                 "allow_transfer": allow_transfer}
                for row in unresolved
            ],
        })
    for assignment in assignments:
        resolution = resolutions[str(assignment.id)]
        if resolution == "delete":
            protect_assignment(db, project, assignment)
            delete_entity_related_rows(db, "assignment", assignment.id)
            db.flush()
            db.delete(assignment)
            db.flush()
        elif allow_transfer:
            try:
                teacher_id = int(resolution)
            except (ValueError, TypeError) as exc:
                raise HTTPException(400, "Hãy chọn giáo viên thay thế hoặc xóa phân công.") from exc
            if teacher_id == assignment.teacher_id:
                raise HTTPException(400, "Giáo viên thay thế phải khác giáo viên đang bỏ môn/xóa.")
            edit_assignment(db, project, assignment, {"teacher_id": teacher_id})
        else:
            raise HTTPException(400, "Phân công liên quan phải được xác nhận xóa.")


def execute(db, project, actor, request):
    """The same business operations are used by isolated preview and atomic apply."""
    before = capture(db, project)
    result = _execute(db, project, actor, request)
    validate_change(db, project, before)
    return result


def validate_change(db, project, before):
    db.flush()
    if schedule_unchanged(before, capture(db, project)):
        return
    report = schedule_integrity_report(db, project, allow_partial=True)
    if not report["valid"]:
        raise HTTPException(409, {"reason": "invalid_schedule", "message": report["message"]})


def _execute(db, project, actor, request):
    """Validate the final state once, after every item of a bulk operation."""
    values = dict(request.values)
    if request.kind == "reset":
        rows = db.scalars(select(Assignment).where(Assignment.project_id == project.id).order_by(Assignment.id)).all()
        for row in rows:
            protect_assignment(db, project, row)
            delete_entity_related_rows(db, "assignment", row.id)
            db.flush()
            db.delete(row)
            db.flush()
        return {"ok": True, "deleted": len(rows)}
    if request.kind == "delete" and values.get("entity_ids"):
        ids = values.pop("entity_ids")
        if not isinstance(ids, list) or not 1 <= len(ids) <= 500 or any(type(eid) is not int or eid <= 0 for eid in ids):
            raise HTTPException(400, "Mỗi lần chỉ được xóa tối đa 500 mục hợp lệ.")
        for eid in dict.fromkeys(ids):
            _execute(db, project, actor, request.model_copy(update={"entity_id": eid, "values": values}))
        return {"ok": True, "deleted": len(set(ids))}
    db.info["change_remove_lesson_ids"] = request.remove_lesson_ids
    if request.kind in {"constraints", "grade_locks"}:
        from app.routers.constraints import constraints, save_session_locks
        from app.services.entities.schemas import ConstraintIn, SessionLocksIn
        if request.kind == "constraints":
            obj = target(db, project, request.entity_type, request.entity_id)
            token = edit_token("availability", obj)
            require_current_edit(request.expected_token, token)
            result = constraints(project.id, ConstraintIn(
                entity_type=request.entity_type, entity_id=obj.id, expected_token=token,
                slots=values.get("slots", []),
            ), actor, db)
        else:
            grade = target(db, project, "grade", request.entity_id)
            token = edit_token("grade_locks", grade)
            require_current_edit(request.expected_token, token)
            result = save_session_locks(project.id, SessionLocksIn(
                grade_id=grade.id, expected_token=token, slots=values.get("slots", []),
                sessions=values.get("sessions", []),
            ), actor, db)
    else:
        obj = target(db, project, request.entity_type, request.entity_id)
        if request.kind != "delete":
            require_current_edit(request.expected_token, current_edit_token(db, request.entity_type, obj))
        if request.kind == "assignment":
            if request.entity_type != "assignment":
                raise HTTPException(400, "Loại phân công không hợp lệ.")
            values["remove_lesson_ids"] = request.remove_lesson_ids.get(str(obj.id), [])
            result = edit_assignment(db, project, obj, values)
        elif request.kind == "entity":
            handler = HANDLERS.get(request.entity_type)
            if not handler:
                raise HTTPException(400, "Loại dữ liệu không hợp lệ.")
            if request.entity_type == "teacher" and "subject_ids" in values:
                wanted = set(validated_subject_ids(db, project.id, values["subject_ids"]))
                assignments = db.scalars(select(Assignment).where(
                    Assignment.project_id == project.id, Assignment.teacher_id == obj.id,
                    Assignment.subject_id.not_in(wanted),
                )).all()
                resolve_assignments(db, project, assignments, request.resolutions, allow_transfer=True)
            limit = {"department": 120, "teacher": 120, "subject": 120, "grade": 80, "class": 80}[request.entity_type]
            name = bounded_text(values.get("name", obj.name), "Tên", limit)
            result = handler(db, project, obj, values, name, project.id)
            if not isinstance(result, JSONResponse):
                synced, displaced, removed, missing = result
                result = {"ok": True, "synced_assignments": synced, "displaced_lessons": len(displaced),
                          "removed_extra_assignments": removed, "missing_grade_assignments": missing,
                          "missing_grade_assignments_count": len(missing)}
        elif request.kind == "delete":
            if request.entity_type == "assignment":
                protect_assignment(db, project, obj)
            else:
                field = {"teacher": Assignment.teacher_id, "class": Assignment.class_id,
                         "subject": Assignment.subject_id}.get(request.entity_type)
                if field is not None:
                    assignments = db.scalars(select(Assignment).where(
                        Assignment.project_id == project.id, field == obj.id)).all()
                    resolve_assignments(db, project, assignments, request.resolutions,
                                        allow_transfer=request.entity_type == "teacher")
                if entity_delete_dependency(db, request.entity_type, obj.id) is not None:
                    # Subject requirements are explicitly included in its cascade preview.
                    if request.entity_type != "subject":
                        raise HTTPException(409, "Hãy chuyển các dữ liệu đang sử dụng mục này trước khi xóa.")
            delete_entity_related_rows(db, request.entity_type, obj.id)
            db.flush()
            db.delete(obj)
            result = {"ok": True}
        else:
            raise HTTPException(400, "Thao tác không hợp lệ.")
    if isinstance(result, JSONResponse):
        content = json.loads(result.body)
        raise HTTPException(result.status_code, content)
    db.flush()
    return result
