from __future__ import annotations

from app.models import Assignment, Lesson, SchoolClass, Subject, Teacher, User
from app.scheduling.rules import (
    assignment_requires_double,
    bounded_int,
    ensure_assignment_hard_feasible,
    normalized_block_mode,
)
from app.services.authentication.sessions import current_user, db_session
from app.services.entities.curriculum.validation import (
    ensure_assignment_matches_grade_requirement,
)
from app.services.entities.deletion import schedule_displacement_confirmation
from app.services.entities.schemas import AssignmentUpdateIn
from app.services.entities.validation import (
    class_assigned_periods,
    ensure_class_load_fits,
    ensure_teacher_load_fits,
    teacher_assigned_periods,
)
from app.services.projects import get_project_for_update
from app.services.schedule_operations.blocks import (
    normalize_assignment_fixed_rows,
    reconcile_assignment_lesson_blocks,
)
from app.services.schedule_operations.feasibility import assignment_completion_feasible
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session


router = APIRouter()


@router.put("/api/projects/{pid}/assignments/{assignment_id}")
def update_assignment(
    pid: int,
    assignment_id: int,
    payload: AssignmentUpdateIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    assignment = db.get(Assignment, assignment_id)
    if not assignment or assignment.project_id != pid:
        raise HTTPException(404)
    periods = bounded_int(payload.periods_per_week, 1, 1, 40, "Số tiết mỗi tuần")
    lessons = db.scalars(
        select(Lesson).where(Lesson.assignment_id == assignment.id)
    ).all()
    scheduled = len(lessons)
    original_lesson_ids = {lesson.id for lesson in lessons}
    subject = db.get(Subject, assignment.subject_id)
    if not subject or subject.project_id != pid:
        raise HTTPException(409, "Môn học của phân công không còn tồn tại")
    try:
        mode = normalized_block_mode(payload.block_mode, periods, subject, project)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    old_periods = assignment.periods_per_week
    old_mode = assignment.block_mode
    if periods < scheduled and not (
        old_mode == "required_double" and mode == "required_double"
    ):
        return JSONResponse(
            {
                "ok": False,
                "message": f"Đang có {scheduled} tiết trên lịch. Hãy gỡ bớt tiết trước khi giảm số tiết/tuần.",
            },
            409,
        )
    teacher = db.get(Teacher, assignment.teacher_id)
    if not teacher or teacher.project_id != pid:
        raise HTTPException(409, "Giáo viên của phân công không còn tồn tại")
    projected_total = (
        teacher_assigned_periods(db, pid, teacher.id) - old_periods + periods
    )
    ensure_teacher_load_fits(db, project, teacher, projected_total)
    school_class = db.get(SchoolClass, assignment.class_id)
    if not school_class or school_class.project_id != pid:
        raise HTTPException(409, "Lớp của phân công không còn tồn tại")
    ensure_assignment_matches_grade_requirement(
        db, project, school_class, subject, periods, mode
    )
    projected_class_total = (
        class_assigned_periods(db, pid, school_class.id) - old_periods + periods
    )
    ensure_class_load_fits(project, school_class, projected_class_total)
    ensure_assignment_hard_feasible(
        project,
        teacher,
        school_class,
        subject,
        periods,
        mode,
    )
    periods_changed = periods != old_periods
    mode_changed = mode != old_mode

    # Reconcile transactionally; any removal must be confirmed before commit.
    assignment.periods_per_week = periods
    assignment.block_mode = mode
    assignment.consecutive_pattern = ""

    if mode_changed or (periods_changed and assignment_requires_double(assignment)):
        lessons, block_error = reconcile_assignment_lesson_blocks(
            db, project, assignment, lessons, old_mode=old_mode
        )
        if block_error:
            db.rollback()
            return JSONResponse({"ok": False, "message": block_error}, 409)
        fixed_error = normalize_assignment_fixed_rows(db, project, assignment, lessons)
        if fixed_error:
            db.rollback()
            return JSONResponse({"ok": False, "message": fixed_error}, 409)

    # Chỉ các thay đổi ảnh hưởng cấu trúc cụm mới cần chứng minh rằng những tiết
    # đã xếp vẫn có ít nhất một cách hoàn thành. Tăng số tiết ở chế độ tự do/
    # ưu tiên chỉ tạo phần còn thiếu trong khay và giữ nguyên toàn bộ lịch cũ.
    if (
        mode_changed or (periods_changed and assignment_requires_double(assignment))
    ) and not assignment_completion_feasible(
        db, project, assignment, [lesson.slot for lesson in lessons]
    ):
        db.rollback()
        return JSONResponse(
            {
                "ok": False,
                "message": "Không thể áp dụng thay đổi vì các tiết hiện có không thể hoàn thành hợp lệ theo chế độ mới và các ràng buộc hiện tại. Lịch cũ được giữ nguyên.",
            },
            409,
        )

    displaced_lesson_ids = sorted(
        original_lesson_ids - {lesson.id for lesson in lessons}
    )
    confirmation = schedule_displacement_confirmation(
        db,
        displaced_lesson_ids,
        confirmed=payload.confirm_displacement,
        confirmed_ids=payload.confirmed_displaced_lesson_ids,
    )
    if confirmation is not None:
        return confirmation
    scheduled_preserved = len(lessons)
    db.commit()
    return {
        "ok": True,
        "scheduled_preserved": scheduled_preserved,
        "displaced_lessons": len(displaced_lesson_ids),
    }
