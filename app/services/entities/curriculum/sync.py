from __future__ import annotations

from app.models import Assignment, Lesson, Project, SchoolClass, Subject, Teacher
from app.scheduling.rules import assignment_requires_double, ensure_assignment_hard_feasible
from app.services.entities.validation import (
    class_assigned_periods,
    ensure_class_load_fits,
    ensure_teacher_load_fits,
    teacher_assigned_periods,
)
from app.services.schedule_operations.blocks import (
    normalize_assignment_fixed_rows,
    reconcile_assignment_lesson_blocks,
)
from app.services.schedule_operations.feasibility import assignment_completion_feasible
from collections import Counter
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session


def sync_assignments_to_grade_requirements(
    db: Session,
    project: Project,
    grade_id: int,
    configs: list[tuple[int, int, str]],
    classes: list[SchoolClass] | None = None,
    displaced_lesson_ids: list[int] | None = None,
) -> int:
    """Đồng bộ phân công hiện có với chương trình khối trong cùng transaction.

    Hàm không tự tạo phân công vì không thể tự chọn giáo viên. Các thay đổi tải
    dạy/tải học được kiểm tra theo tổng delta trước khi sửa ORM objects; các
    ghim và tính khả thi của lịch hiện tại cũng được kiểm tra trước khi commit.
    """
    if classes is None:
        classes = db.scalars(
            select(SchoolClass).where(
                SchoolClass.project_id == project.id,
                SchoolClass.grade_id == grade_id,
            )
        ).all()
    if not classes or not configs:
        return 0

    class_by_id = {row.id: row for row in classes}
    class_ids = list(class_by_id)
    config_by_subject = {
        subject_id: (int(periods), mode or "free")
        for subject_id, periods, mode in configs
    }
    subject_ids = list(config_by_subject)
    assignments = db.scalars(
        select(Assignment).where(
            Assignment.project_id == project.id,
            Assignment.class_id.in_(class_ids),
            Assignment.subject_id.in_(subject_ids),
        )
    ).all()
    if not assignments:
        return 0

    subjects = {
        row.id: row
        for row in db.scalars(
            select(Subject).where(
                Subject.project_id == project.id,
                Subject.id.in_(subject_ids),
            )
        ).all()
    }
    teacher_ids = {row.teacher_id for row in assignments}
    teachers = {
        row.id: row
        for row in db.scalars(
            select(Teacher).where(
                Teacher.project_id == project.id,
                Teacher.id.in_(teacher_ids),
            )
        ).all()
    }

    changes = []
    teacher_deltas: Counter[int] = Counter()
    class_deltas: Counter[int] = Counter()
    for assignment in assignments:
        desired = config_by_subject.get(assignment.subject_id)
        if desired is None:
            continue
        periods, mode = desired
        old_periods = int(assignment.periods_per_week)
        old_mode = assignment.block_mode or "free"
        if old_periods == periods and old_mode == mode:
            continue

        school_class = class_by_id.get(assignment.class_id)
        subject = subjects.get(assignment.subject_id)
        teacher = teachers.get(assignment.teacher_id)
        if not school_class or not subject or not teacher:
            raise HTTPException(
                409,
                "Không thể đồng bộ chương trình khối vì có phân công tham chiếu dữ liệu không còn tồn tại.",
            )

        lessons = db.scalars(
            select(Lesson).where(Lesson.assignment_id == assignment.id)
        ).all()
        scheduled = len(lessons)
        if periods < scheduled and not (
            old_mode == "required_double" and mode == "required_double"
        ):
            raise HTTPException(
                409,
                f"Không thể đổi chương trình: {school_class.name} – {subject.name} "
                f"đang có {scheduled} tiết trên lịch nhưng chuẩn mới chỉ còn {periods} tiết/tuần. "
                "Hãy gỡ bớt tiết trên lịch trước.",
            )

        ensure_assignment_hard_feasible(
            project, teacher, school_class, subject, periods, mode
        )
        delta = periods - old_periods
        teacher_deltas[teacher.id] += delta
        class_deltas[school_class.id] += delta
        changes.append(
            (
                assignment,
                school_class,
                subject,
                teacher,
                lessons,
                periods,
                mode,
                old_periods,
                old_mode,
            )
        )

    for teacher_id, delta in teacher_deltas.items():
        teacher = teachers[teacher_id]
        ensure_teacher_load_fits(
            db,
            project,
            teacher,
            teacher_assigned_periods(db, project.id, teacher_id) + delta,
        )
    for class_id, delta in class_deltas.items():
        school_class = class_by_id[class_id]
        ensure_class_load_fits(
            project,
            school_class,
            class_assigned_periods(db, project.id, class_id) + delta,
        )

    for (
        assignment,
        school_class,
        subject,
        _teacher,
        lessons,
        periods,
        mode,
        old_periods,
        old_mode,
    ) in changes:
        periods_changed = periods != old_periods
        mode_changed = mode != old_mode
        assignment.periods_per_week = periods
        assignment.block_mode = mode
        assignment.consecutive_pattern = ""

        if mode_changed or (periods_changed and assignment_requires_double(assignment)):
            original_lesson_ids = {lesson.id for lesson in lessons}
            lessons, block_error = reconcile_assignment_lesson_blocks(
                db, project, assignment, lessons, old_mode=old_mode
            )
            if displaced_lesson_ids is not None:
                displaced_lesson_ids.extend(
                    sorted(original_lesson_ids - {lesson.id for lesson in lessons})
                )
            if block_error:
                raise HTTPException(
                    409,
                    f"Không thể đổi chương trình cho {school_class.name} – {subject.name}: {block_error}",
                )
            fixed_error = normalize_assignment_fixed_rows(
                db, project, assignment, lessons
            )
            if fixed_error:
                raise HTTPException(
                    409,
                    f"Không thể đổi chương trình cho {school_class.name} – {subject.name}: {fixed_error}",
                )
            if not assignment_completion_feasible(
                db, project, assignment, [lesson.slot for lesson in lessons]
            ):
                raise HTTPException(
                    409,
                    f"Không thể đổi chương trình cho {school_class.name} – {subject.name} vì "
                    "các tiết hiện có không thể hoàn thành hợp lệ theo chế độ mới và các ràng buộc hiện tại.",
                )

    return len(changes)
