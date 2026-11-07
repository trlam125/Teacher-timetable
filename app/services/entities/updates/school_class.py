from __future__ import annotations

from app.models import (
    Assignment, FixedLesson, Grade, GradeSubjectRequirement, Lesson,
    Project, SchoolClass, Subject, Teacher,
)
from app.scheduling.rules import (
    class_grade_blocked_slots,
    ensure_assignment_hard_feasible,
    fixed_row_size,
)
from app.services.entities.curriculum.comparison import (
    grade_requirement_extra_assignments,
    grade_requirement_missing_assignments,
)
from app.services.entities.curriculum.sync import sync_assignments_to_grade_requirements
from app.services.entities.deletion import delete_entity_related_rows, extra_assignment_removal_confirmation
from app.services.entities.validation import (
    class_assigned_periods,
    ensure_class_load_fits,
    ensure_grade_program_fits,
    ensure_unique_project_name,
)
from app.services.schedule_operations.feasibility import ensure_pinned_assignments_feasible
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.services.change_impact.managed import managed_edit
from app.services.change_impact.reconcile import remove_class_conflicts


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
    changing_grade = grade_id != obj.grade_id
    if changing_grade and grade_id is not None:
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
        ensure_grade_program_fits(project, db.get(Grade, grade_id), sum(row[1] for row in proposed_configs))
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
        confirmation = extra_assignment_removal_confirmation(
            db, extra_assignments, d, reason="class_grade_extra_assignments",
        )
        if confirmation is not None:
            return confirmation

        obj.grade = db.get(Grade, grade_id)
        if extra_assignments:
            for item in extra_assignments:
                assignment = db.get(Assignment, item["assignment_id"])
                if not assignment or assignment.project_id != pid:
                    continue
                delete_entity_related_rows(db, "assignment", assignment.id)
                db.delete(assignment)
                removed_extra_assignments += 1
        db.flush()
        synced_assignments += sync_assignments_to_grade_requirements(
            db,
            project,
            grade_id,
            proposed_configs,
            classes=[obj],
            displaced_lesson_ids=displaced_lesson_ids,
        )
    obj.name = name
    obj.grade_id = grade_id
    if changing_grade:
        obj.grade = db.get(Grade, grade_id) if grade_id is not None else None
        if managed_edit(db):
            db.flush()
            remove_class_conflicts(db, project, obj)
        ensure_class_load_fits(project, obj, class_assigned_periods(db, pid, obj.id))
        blocked = class_grade_blocked_slots(obj)
        assignments = db.scalars(
            select(Assignment).where(
                Assignment.project_id == pid, Assignment.class_id == obj.id,
            )
        ).all()
        for assignment in assignments:
            teacher = db.get(Teacher, assignment.teacher_id)
            subject = db.get(Subject, assignment.subject_id)
            if teacher and subject:
                ensure_assignment_hard_feasible(
                    project, teacher, obj, subject,
                    assignment.periods_per_week, assignment.block_mode,
                )
            lessons = db.scalars(
                select(Lesson).where(
                    Lesson.project_id == pid, Lesson.assignment_id == assignment.id,
                )
            ).all()
            fixed_rows = db.scalars(
                select(FixedLesson).where(
                    FixedLesson.project_id == pid, FixedLesson.assignment_id == assignment.id,
                )
            ).all()
            conflicts = any(row.slot in blocked for row in lessons)
            for row in fixed_rows:
                size = fixed_row_size(project, assignment, row, lessons)
                conflicts = (
                    conflicts or size < 1
                    or bool(blocked.intersection(range(row.slot, row.slot + size)))
                )
            if conflicts:
                raise HTTPException(
                    409,
                    "Lớp có tiết đã xếp hoặc cố định xung đột với khóa lịch của khối mới. "
                    "Hãy chuyển/gỡ các tiết đó hoặc điều chỉnh khóa khối trước.",
                )
        ensure_pinned_assignments_feasible(db, project, assignments)
    return synced_assignments, displaced_lesson_ids, removed_extra_assignments, missing_grade_assignments
