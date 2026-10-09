from __future__ import annotations

from app.models import Assignment, Grade, GradeSubjectRequirement, Project, SchoolClass
from app.services.entities.curriculum.comparison import (
    grade_requirement_extra_assignments,
    grade_requirement_missing_assignments,
)
from app.services.entities.curriculum.sync import sync_assignments_to_grade_requirements
from app.services.entities.deletion import delete_entity_related_rows
from app.services.entities.validation import ensure_unique_project_name
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session


def update_class_fields(db: Session, project: Project, obj, d: dict, name: str, pid: int):
    synced_assignments = 0
    displaced_lesson_ids: list[int] = []
    removed_extra_assignments = 0
    missing_grade_assignments: list[str] = []
    ensure_unique_project_name(
        db, SchoolClass, pid, name, "Lớp học", exclude_id=obj.id
    )
    if "grade_id" in d:
        grade_id = d.get("grade_id") or None
        if grade_id is not None:
            try:
                grade_id = int(grade_id)
            except (TypeError, ValueError) as exc:
                raise HTTPException(400, "Khối lớp không hợp lệ") from exc
            grade = db.get(Grade, grade_id)
            if not grade or grade.project_id != pid:
                raise HTTPException(400, "Khối lớp không hợp lệ")
    else:
        grade_id = obj.grade_id
    if grade_id != obj.grade_id and grade_id is not None:
        proposed_rows = db.scalars(
            select(GradeSubjectRequirement).where(
                GradeSubjectRequirement.project_id == pid,
                GradeSubjectRequirement.grade_id == grade_id,
            )
        ).all()
        proposed_configs = [
            (row.subject_id, int(row.periods_per_week), row.block_mode or "free")
            for row in proposed_rows
        ]
        missing_grade_assignments = grade_requirement_missing_assignments(
            db,
            project,
            grade_id,
            proposed_configs,
            classes=[obj],
        )

        extra_assignments = grade_requirement_extra_assignments(
            db, project, grade_id, classes=[obj]
        )
        if extra_assignments and d.get("remove_extra_assignments") is not True:
            grade = db.get(Grade, grade_id)
            preview = "; ".join(
                f"{item['class_name']} – {item['subject_name']}"
                for item in extra_assignments[:5]
            )
            suffix = (
                f"; và {len(extra_assignments) - 5} phân công khác"
                if len(extra_assignments) > 5
                else ""
            )
            return JSONResponse(
                {
                    "ok": False,
                    "reason": "class_grade_extra_assignments",
                    "extra_assignments": extra_assignments,
                    "message": (
                        f"{obj.name} đang có phân công không thuộc chương trình "
                        f"{grade.name if grade else 'khối mới'}: {preview}{suffix}. "
                        "Nếu tiếp tục, các phân công này và các tiết đã xếp/ghim tương ứng sẽ bị xóa."
                    ),
                },
                409,
            )

        synced_assignments += sync_assignments_to_grade_requirements(
            db,
            project,
            grade_id,
            proposed_configs,
            classes=[obj],
            displaced_lesson_ids=displaced_lesson_ids,
        )
        if extra_assignments:
            for item in extra_assignments:
                assignment = db.get(Assignment, item["assignment_id"])
                if not assignment or assignment.project_id != pid:
                    continue
                delete_entity_related_rows(db, "assignment", assignment.id)
                db.delete(assignment)
                removed_extra_assignments += 1
    obj.name = name
    obj.grade_id = grade_id
    return synced_assignments, displaced_lesson_ids, removed_extra_assignments, missing_grade_assignments
