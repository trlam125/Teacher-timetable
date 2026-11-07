from fastapi import HTTPException
from sqlalchemy import select

from app.models import Assignment, SchoolClass, Subject, Teacher, TeacherSubject
from app.scheduling.rules import bounded_int, ensure_assignment_hard_feasible, normalized_block_mode
from app.services.entities.curriculum.validation import ensure_assignment_matches_grade_requirement
from app.services.entities.validation import class_assigned_periods, ensure_class_load_fits
from app.services.change_impact.reconcile import reconcile_edit


def edit_assignment(db, project, assignment, values, *, check_curriculum=True):
    raw_teacher = values.get("teacher_id")
    teacher_id = assignment.teacher_id if raw_teacher is None else bounded_int(raw_teacher, 0, 1, 2147483647, "Giáo viên")
    teacher = db.get(Teacher, teacher_id)
    subject = db.get(Subject, assignment.subject_id)
    school_class = db.get(SchoolClass, assignment.class_id)
    if not all(row and row.project_id == project.id for row in (teacher, subject, school_class)):
        raise HTTPException(400, "Giáo viên, môn hoặc lớp không thuộc project này.")
    if db.scalar(select(TeacherSubject.id).where(
        TeacherSubject.project_id == project.id, TeacherSubject.teacher_id == teacher.id,
        TeacherSubject.subject_id == subject.id,
    )) is None:
        raise HTTPException(409, f"{teacher.name} chưa được cấu hình dạy môn {subject.name}.")
    periods = bounded_int(values.get("periods_per_week", assignment.periods_per_week), 1, 1, 40, "Số tiết/tuần")
    try:
        mode = normalized_block_mode(values.get("block_mode", assignment.block_mode), periods, subject, project)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if check_curriculum:
        ensure_assignment_matches_grade_requirement(db, project, school_class, subject, periods, mode)
    ensure_class_load_fits(project, school_class,
                          class_assigned_periods(db, project.id, school_class.id) - assignment.periods_per_week + periods)
    ensure_assignment_hard_feasible(project, teacher, school_class, subject, periods, mode)
    old_mode, old_teacher = assignment.block_mode, assignment.teacher_id
    assignment.teacher_id = teacher.id
    assignment.periods_per_week = periods
    assignment.block_mode = mode
    assignment.consecutive_pattern = ""
    db.flush()
    rows = reconcile_edit(db, project, assignment, old_mode=old_mode,
                          selected_ids=values.get("remove_lesson_ids"), teacher_changed=teacher.id != old_teacher)
    return {"ok": True, "scheduled_preserved": len(rows)}
