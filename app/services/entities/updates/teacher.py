from __future__ import annotations

from app.models import Assignment, Department, Lesson, Project, SchoolClass, Subject
from app.scheduling.rules import bounded_int, ensure_assignment_hard_feasible
from app.services.entities.validation import (
    ensure_teacher_load_fits,
    ensure_unique_teacher_short_name,
    replace_teacher_subjects,
    teacher_assigned_periods,
    validated_subject_ids,
)
from app.services.web import bounded_text
from collections import Counter
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session


def update_teacher_fields(db: Session, project: Project, obj, d: dict, name: str, pid: int):
    synced_assignments = 0
    displaced_lesson_ids: list[int] = []
    removed_extra_assignments = 0
    missing_grade_assignments: list[str] = []
    short_name = bounded_text(d.get("short_name", ""), "Tên ngắn", 30)
    ensure_unique_teacher_short_name(db, pid, short_name, exclude_id=obj.id)
    if "department_id" in d:
        department_id = d.get("department_id") or None
        if department_id is not None:
            try:
                department_id = int(department_id)
            except (TypeError, ValueError) as exc:
                raise HTTPException(400, "Tổ chuyên môn không hợp lệ") from exc
            department = db.get(Department, department_id)
            if not department or department.project_id != pid:
                raise HTTPException(400, "Tổ chuyên môn không hợp lệ")
    else:
        department_id = obj.department_id
    new_max_periods_day = bounded_int(
        d.get("max_periods_day"),
        min(obj.max_periods_day, project.sessions * project.periods_per_session),
        1,
        project.sessions * project.periods_per_session,
        "Số tiết tối đa mỗi ngày",
    )
    assignment_ids = set(
        db.scalars(
            select(Assignment.id).where(
                Assignment.project_id == pid,
                Assignment.teacher_id == obj.id,
            )
        ).all()
    )
    if assignment_ids:
        ppd = project.sessions * project.periods_per_session
        daily_counts = Counter(
            slot // ppd
            for slot in db.scalars(
                select(Lesson.slot).where(
                    Lesson.project_id == pid,
                    Lesson.assignment_id.in_(assignment_ids),
                )
            ).all()
        )
        highest_current = max(daily_counts.values(), default=0)
        if highest_current > new_max_periods_day:
            raise HTTPException(
                409,
                f"Không thể giảm còn {new_max_periods_day} tiết/ngày vì lịch hiện tại có ngày giáo viên đang dạy {highest_current} tiết. Hãy điều chỉnh lịch trước.",
            )
    assigned_total = teacher_assigned_periods(db, pid, obj.id)
    ensure_teacher_load_fits(
        db, project, obj, assigned_total, max_periods_day=new_max_periods_day
    )
    for assignment in db.scalars(
        select(Assignment).where(
            Assignment.project_id == pid,
            Assignment.teacher_id == obj.id,
        )
    ).all():
        school_class = db.get(SchoolClass, assignment.class_id)
        subject = db.get(Subject, assignment.subject_id)
        if school_class and subject:
            ensure_assignment_hard_feasible(
                project,
                obj,
                school_class,
                subject,
                assignment.periods_per_week,
                assignment.block_mode,
                max_periods_day=new_max_periods_day,
            )
    if "subject_ids" in d:
        teacher_subject_ids = validated_subject_ids(db, pid, d.get("subject_ids"))
        assigned_subject_ids = set(
            db.scalars(
                select(Assignment.subject_id).where(
                    Assignment.project_id == pid,
                    Assignment.teacher_id == obj.id,
                )
            ).all()
        )
        removed_in_use = assigned_subject_ids - set(teacher_subject_ids)
        if removed_in_use:
            names = db.scalars(
                select(Subject.name).where(Subject.id.in_(removed_in_use))
            ).all()
            raise HTTPException(
                409,
                "Không thể bỏ môn đang có phân công: "
                + ", ".join(names)
                + ". Hãy xóa/chuyển phân công trước.",
            )
        replace_teacher_subjects(db, pid, obj.id, teacher_subject_ids)
    obj.name = name
    obj.short_name = short_name
    obj.department_id = department_id
    obj.max_periods_day = new_max_periods_day
    return synced_assignments, displaced_lesson_ids, removed_extra_assignments, missing_grade_assignments
