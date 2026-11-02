from __future__ import annotations

from app.logic import fixed_group_validation_error
from app.models import Assignment, FixedLesson, Lesson, Project, SchoolClass, Subject, Teacher
from app.scheduling.rules import (
    assignment_groups,
    assignment_prefers_double,
    assignment_requires_double,
    class_blocked_slots,
    fixed_row_size,
    parse_slots,
)
from collections import Counter, defaultdict
from sqlalchemy import select
from sqlalchemy.orm import Session
from types import SimpleNamespace
from fastapi import HTTPException
from app.services.schedule_operations.blocks import fixed_coverage_slots


def assignment_feasibility_context(
    db: Session,
    project: Project,
    assignment: Assignment,
    *,
    fixed_only: bool = False,
    project_blocked_slots: set[int] | None = None,
    teacher_unavailable_slots: set[int] | None = None,
    class_unavailable_slots: set[int] | None = None,
):
    """Preload immutable inputs reused while evaluating many candidate slots."""
    pps = project.periods_per_session
    ppd = project.sessions * pps
    teacher = db.get(Teacher, assignment.teacher_id)
    school_class = db.get(SchoolClass, assignment.class_id)
    subject = db.get(Subject, assignment.subject_id)
    if not teacher or not school_class or not subject:
        return None

    assignments = {
        row.id: row
        for row in db.scalars(
            select(Assignment).where(Assignment.project_id == project.id)
        ).all()
    }
    all_lessons = db.scalars(select(Lesson).where(Lesson.project_id == project.id)).all()
    lessons = all_lessons
    if fixed_only:
        coverage = fixed_coverage_slots(db, project)
        lessons = [row for row in all_lessons if row.locked or row.slot in coverage.get(row.assignment_id, set())]
        present = {(row.assignment_id, row.slot) for row in lessons}
        lessons.extend(
            SimpleNamespace(assignment_id=assignment_id, slot=slot, locked=True)
            for assignment_id, slots in coverage.items() for slot in slots
            if (assignment_id, slot) not in present
        )
    forbidden = (
        (parse_slots(project.blocked_slots_json) if project_blocked_slots is None else set(project_blocked_slots))
        | (parse_slots(teacher.unavailable_json) if teacher_unavailable_slots is None else set(teacher_unavailable_slots))
        | (class_blocked_slots(school_class) if class_unavailable_slots is None else set(class_unavailable_slots))
    )
    teacher_day = Counter()
    subject_masks = defaultdict(int)
    for lesson in lessons:
        if lesson.assignment_id == assignment.id:
            continue
        other = assignments.get(lesson.assignment_id)
        if not other:
            continue
        if other.teacher_id == assignment.teacher_id:
            forbidden.add(lesson.slot)
            teacher_day[lesson.slot // ppd] += 1
        if other.class_id == assignment.class_id:
            forbidden.add(lesson.slot)
            if other.subject_id == assignment.subject_id:
                subject_masks[lesson.slot // pps] |= 1 << (lesson.slot % pps)

    fixed_rows = db.scalars(
        select(FixedLesson).where(
            FixedLesson.project_id == project.id,
            FixedLesson.assignment_id == assignment.id,
        )
    ).all()
    same_lessons = [row for row in lessons if row.assignment_id == assignment.id]
    specs = [
        (row.slot, fixed_row_size(project, assignment, row, [lesson for lesson in all_lessons if lesson.assignment_id == assignment.id]))
        for row in fixed_rows
    ]
    fixed_error = fixed_group_validation_error(
        assignment_groups(assignment),
        specs,
        days=project.days,
        sessions=project.sessions,
        periods_per_session=pps,
    )
    return {
        "teacher": teacher,
        "subject": subject,
        "forbidden": forbidden,
        "teacher_day": teacher_day,
        "subject_masks": subject_masks,
        "specs": specs,
        "same_lessons": same_lessons,
        "fixed_error": fixed_error,
    }


def assignment_completion_feasible(
    db: Session,
    project: Project,
    assignment: Assignment,
    proposed_slots: list[int] | set[int],
    *,
    enforce_pattern: bool = True,
    context=None,
) -> bool:
    """Exact bounded DP over session masks (at most 2**8 per session).

    Avoid exploring permutations of every remaining period. A state only needs
    the number of periods and compulsory singles used; day budgets are applied
    before combining days. Existing and fixed slots must be covered exactly.
    """
    values = list(proposed_slots)
    current = set(values)
    total = int(assignment.periods_per_week)
    pps = project.periods_per_session
    ppd = project.sessions * pps
    maximum = project.days * ppd
    if len(values) != len(current) or len(current) > total:
        return False
    if any(slot < 0 or slot >= maximum for slot in current):
        return False
    feasibility = context or assignment_feasibility_context(db, project, assignment)
    if not feasibility or feasibility["fixed_error"]:
        return False
    teacher = feasibility["teacher"]
    subject = feasibility["subject"]
    forbidden = feasibility["forbidden"]
    teacher_day = feasibility["teacher_day"]
    subject_masks = feasibility["subject_masks"]
    specs = feasibility["specs"]
    same_lessons = feasibility["same_lessons"]
    required = set(current)
    forced_by_session = defaultdict(dict)
    for start, size in specs:
        required.update(range(start, start + size))
        forced_by_session[start // pps][start % pps] = size
    # A locked row without metadata must also stay covered (legacy projects).
    required.update(row.slot for row in same_lessons if row.locked)
    if len(required) > total or required.intersection(forbidden):
        return False
    double = assignment_requires_double(assignment) and enforce_pattern
    single_limit = total % 2 if double else 0
    max_run = pps
    reachable = {(0, 0)}
    for day in range(project.days):
        budget = min(total, ppd - teacher_day[day])
        if budget < 0:
            return False
        day_options = {(0, 0)}
        for session in range(project.sessions):
            key = day * project.sessions + session
            base = key * pps
            allowed = sum(1 << i for i in range(pps) if base + i not in forbidden)
            mandatory = sum(1 << i for i in range(pps) if base + i in required)
            forced = forced_by_session[key]
            options = set()
            mask = allowed
            while True:
                count = mask.bit_count()
                if mask & mandatory == mandatory and count <= budget:
                    occupied = mask | subject_masks[key]
                    run = longest = 0
                    for i in range(pps):
                        run = run + 1 if occupied & (1 << i) else 0
                        longest = max(longest, run)
                    if longest <= max_run:
                        singles = 0
                        if double:
                            # Fixed groups split a run into independent segments;
                            # never let a new pair consume half an explicit pin.
                            cursor = 0
                            while cursor < pps:
                                if not mask & (1 << cursor):
                                    cursor += 1
                                elif cursor in forced:
                                    size = forced[cursor]
                                    singles += size % 2
                                    cursor += size
                                else:
                                    start = cursor
                                    while (
                                        cursor < pps
                                        and mask & (1 << cursor)
                                        and cursor not in forced
                                    ):
                                        cursor += 1
                                    singles += (cursor - start) % 2
                        if singles <= single_limit:
                            options.add((count, singles))
                if mask == 0:
                    break
                mask = (mask - 1) & allowed
            day_options = {
                (used + added, odd + extra)
                for used, odd in day_options
                for added, extra in options
                if used + added <= budget and odd + extra <= single_limit
            }
            if not day_options:
                return False
        reachable = {
            (used + added, odd + extra)
            for used, odd in reachable
            for added, extra in day_options
            if used + added <= total and odd + extra <= single_limit
        }
        if not reachable:
            return False
    return (total, single_limit) in reachable


def ensure_pinned_assignments_feasible(
    db: Session, project: Project, assignments: list[Assignment], *,
    project_blocked_slots: set[int] | None = None,
    teacher_unavailable: dict[int, set[int]] | None = None,
    class_unavailable: dict[int, set[int]] | None = None,
) -> None:
    """Check proposed rules with pins held and all movable lessons free to move."""
    for assignment in assignments:
        context = assignment_feasibility_context(
            db, project, assignment, fixed_only=True,
            project_blocked_slots=project_blocked_slots,
            teacher_unavailable_slots=(teacher_unavailable or {}).get(assignment.teacher_id),
            class_unavailable_slots=(class_unavailable or {}).get(assignment.class_id),
        )
        if not assignment_completion_feasible(db, project, assignment, [], context=context):
            school_class = db.get(SchoolClass, assignment.class_id)
            subject = db.get(Subject, assignment.subject_id)
            raise HTTPException(409,
                f"Không thể hoàn thành {school_class.name if school_class else '?'} – "
                f"{subject.name if subject else '?'} khi giữ các tiết cố định. "
                "Hãy điều chỉnh khóa/tiết tránh hoặc bỏ ghim liên quan trước.")


def assignment_pattern_label(assignment: Assignment):
    if assignment_requires_double(assignment):
        return (
            "bắt buộc tiết đôi ("
            + " + ".join(str(value) for value in assignment_groups(assignment))
            + ")"
        )
    if assignment_prefers_double(assignment):
        return "ưu tiên tiết đôi"
    return "xếp tiết tự do"
