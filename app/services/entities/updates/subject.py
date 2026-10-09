from __future__ import annotations

from app.models import (
    Assignment,
    GradeSubjectRequirement,
    Lesson,
    Project,
    SchoolClass,
    Subject,
    Teacher,
)
from app.scheduling.rules import (
    assignment_prefers_double,
    bounded_int,
    ensure_assignment_hard_feasible,
    required_double_structure_feasible,
)
from app.services.entities.validation import ensure_unique_project_name
from app.services.web import bounded_text
from collections import defaultdict
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session


def update_subject_fields(db: Session, project: Project, obj, d: dict, name: str, pid: int):
    synced_assignments = 0
    displaced_lesson_ids: list[int] = []
    removed_extra_assignments = 0
    missing_grade_assignments: list[str] = []
    ensure_unique_project_name(db, Subject, pid, name, "Môn học", exclude_id=obj.id)
    short_name = bounded_text(d.get("short_name", ""), "Tên rút gọn", 20)
    new_max_consecutive = bounded_int(
        d.get("max_consecutive"),
        min(obj.max_consecutive, project.periods_per_session),
        1,
        project.periods_per_session,
        "Số tiết liên tiếp tối đa",
    )
    assignments = db.scalars(
        select(Assignment).where(
            Assignment.project_id == pid,
            Assignment.subject_id == obj.id,
        )
    ).all()
    incompatible_assignments = [
        assignment.id
        for assignment in assignments
        if assignment_prefers_double(assignment)
        and assignment.periods_per_week >= 2
        and new_max_consecutive < 2
    ]

    for assignment in assignments:
        teacher = db.get(Teacher, assignment.teacher_id)
        school_class = db.get(SchoolClass, assignment.class_id)
        if not teacher or not school_class:
            raise HTTPException(
                409,
                "Không thể đổi giới hạn tiết liên tiếp vì có phân công tham chiếu dữ liệu không còn tồn tại.",
            )
        ensure_assignment_hard_feasible(
            project,
            teacher,
            school_class,
            obj,
            assignment.periods_per_week,
            assignment.block_mode,
            max_consecutive=new_max_consecutive,
        )
    incompatible_grade_requirements = db.scalars(
        select(GradeSubjectRequirement).where(
            GradeSubjectRequirement.project_id == pid,
            GradeSubjectRequirement.subject_id == obj.id,
            GradeSubjectRequirement.block_mode == "required_double",
        )
    ).all()
    incompatible_grade_requirements = [
        row.id
        for row in incompatible_grade_requirements
        if not required_double_structure_feasible(
            project, row.periods_per_week, new_max_consecutive
        )
    ]

    assignment_by_id = {assignment.id: assignment for assignment in assignments}
    periods_by_class_session = defaultdict(list)
    periods_per_day = project.sessions * project.periods_per_session
    if assignment_by_id:
        lessons = db.scalars(
            select(Lesson).where(
                Lesson.project_id == pid,
                Lesson.assignment_id.in_(list(assignment_by_id)),
            )
        ).all()
        for lesson in lessons:
            assignment = assignment_by_id.get(lesson.assignment_id)
            if not assignment:
                continue
            day = lesson.slot // periods_per_day
            inside_day = lesson.slot % periods_per_day
            session = inside_day // project.periods_per_session
            period = inside_day % project.periods_per_session
            periods_by_class_session[(assignment.class_id, day, session)].append(
                period
            )

    violating_class_sessions = 0
    for periods in periods_by_class_session.values():
        longest = run = 0
        previous = None
        for period in sorted(set(periods)):
            run = run + 1 if previous is not None and period == previous + 1 else 1
            longest = max(longest, run)
            previous = period
        if longest > new_max_consecutive:
            violating_class_sessions += 1

    if (
        incompatible_assignments
        or incompatible_grade_requirements
        or violating_class_sessions
    ):
        details = []
        if incompatible_assignments:
            details.append(
                f"{len(incompatible_assignments)} phân công đang dùng chế độ tiết đôi"
            )
        if incompatible_grade_requirements:
            details.append(
                f"{len(incompatible_grade_requirements)} cấu hình chương trình khối bắt buộc tiết đôi "
                "sẽ không còn cách xếp hợp lệ"
            )
        if violating_class_sessions:
            details.append(
                f"{violating_class_sessions} buổi của lớp đang có cụm môn học dài hơn"
            )
        raise HTTPException(
            409,
            f"Không thể giảm còn {new_max_consecutive} tiết liên tiếp vì "
            + " và ".join(details)
            + ". Hãy điều chỉnh phân công, chương trình khối hoặc lịch hiện tại trước.",
        )
    obj.name = name
    obj.short_name = short_name
    obj.max_consecutive = new_max_consecutive
    return synced_assignments, displaced_lesson_ids, removed_extra_assignments, missing_grade_assignments
