from __future__ import annotations

from app.models import Assignment, FixedLesson, Lesson, Project, SchoolClass, Subject, Teacher
from app.scheduling.rules import (
    assignment_requires_double,
    parse_slots,
    required_double_block_state,
)
from app.services.schedule_operations.blocks import fixed_coverage_slots
from app.services.schedule_validation import schedule_input_validation_report
from collections import Counter, defaultdict
from sqlalchemy import select
from sqlalchemy.orm import Session


def _minimal_schedule_invalid_lesson_analysis(
    db: Session,
    project: Project,
    assignments: list[Assignment],
    lessons: list[Lesson],
) -> list[tuple[Lesson, str]]:
    """Return only the lessons that must be rejected, with UI-safe reasons.

    Lessons are evaluated in the same deterministic order used by integrity
    validation: locked lessons first, then movable lessons by slot/id. A lesson
    is marked invalid only when adding that lesson would introduce a hard
    conflict. This keeps aggregate limits (daily teacher load and consecutive
    subject periods) minimal instead of incorrectly marking the whole group.
    """
    assignment_by_id = {assignment.id: assignment for assignment in assignments}
    teachers = {
        teacher.id: teacher
        for teacher in db.scalars(
            select(Teacher).where(Teacher.project_id == project.id)
        ).all()
    }
    classes = {
        school_class.id: school_class
        for school_class in db.scalars(
            select(SchoolClass).where(SchoolClass.project_id == project.id)
        ).all()
    }
    subjects = {
        subject.id: subject
        for subject in db.scalars(
            select(Subject).where(Subject.project_id == project.id)
        ).all()
    }
    teacher_unavailable = {
        teacher_id: parse_slots(teacher.unavailable_json)
        for teacher_id, teacher in teachers.items()
    }
    class_unavailable = {
        class_id: parse_slots(school_class.unavailable_json)
        for class_id, school_class in classes.items()
    }

    maximum = project.days * project.sessions * project.periods_per_session
    periods_per_day = project.sessions * project.periods_per_session
    blocked = parse_slots(project.blocked_slots_json)

    teacher_slot_busy: set[tuple[int, int]] = set()
    class_slot_busy: set[tuple[int, int]] = set()
    teacher_day_counts: Counter[tuple[int, int]] = Counter()
    class_subject_session_periods: dict[tuple[int, int, int, int], set[int]] = (
        defaultdict(set)
    )
    invalid: list[tuple[Lesson, str]] = []

    def reject(lesson: Lesson, reason: str) -> None:
        invalid.append((lesson, reason))

    def exceeds_subject_run(periods: set[int], candidate: int, limit: int) -> bool:
        ordered = sorted(periods | {candidate})
        longest = current = 0
        previous = None
        for period in ordered:
            current = (
                current + 1 if previous is not None and period == previous + 1 else 1
            )
            longest = max(longest, current)
            previous = period
        return longest > limit

    ordered_lessons = sorted(
        lessons,
        key=lambda lesson: (
            0 if bool(lesson.locked) else 1,
            int(lesson.slot),
            int(lesson.id or 0),
        ),
    )

    for lesson in ordered_lessons:
        assignment = assignment_by_id.get(lesson.assignment_id)
        if not assignment:
            reject(lesson, "Tiết học tham chiếu phân công không còn tồn tại.")
            continue

        teacher = teachers.get(assignment.teacher_id)
        school_class = classes.get(assignment.class_id)
        subject = subjects.get(assignment.subject_id)
        if not teacher or not school_class or not subject:
            reject(lesson, "Phân công không còn đầy đủ lớp, môn hoặc giáo viên.")
            continue

        slot = int(lesson.slot)
        if slot < 0 or slot >= maximum:
            reject(lesson, "Ô thời khóa biểu không hợp lệ.")
            continue
        if slot in blocked:
            reject(lesson, "Tiết này đã bị khóa toàn trường.")
            continue
        if slot in teacher_unavailable[teacher.id]:
            reject(lesson, f"Giáo viên {teacher.name} không thể dạy ở tiết này.")
            continue
        if slot in class_unavailable[school_class.id]:
            reject(lesson, f"Lớp {school_class.name} không học ở tiết này.")
            continue

        day = slot // periods_per_day
        inside_day = slot % periods_per_day
        session = inside_day // project.periods_per_session
        period = inside_day % project.periods_per_session
        teacher_slot_key = (assignment.teacher_id, slot)
        class_slot_key = (assignment.class_id, slot)
        teacher_day_key = (assignment.teacher_id, day)
        subject_run_key = (assignment.class_id, assignment.subject_id, day, session)

        if teacher_slot_key in teacher_slot_busy:
            reject(lesson, f"Trùng lịch giáo viên {teacher.name} trong cùng một tiết.")
            continue
        if class_slot_key in class_slot_busy:
            reject(lesson, f"Trùng lịch lớp {school_class.name} trong cùng một tiết.")
            continue

        daily_limit = int(teacher.max_periods_day or 0)
        if teacher_day_counts[teacher_day_key] >= daily_limit:
            reject(
                lesson,
                f"Giáo viên {teacher.name} vượt giới hạn {daily_limit} tiết/ngày.",
            )
            continue

        consecutive_limit = int(subject.max_consecutive or 0)
        if exceeds_subject_run(
            class_subject_session_periods[subject_run_key],
            period,
            consecutive_limit,
        ):
            reject(
                lesson,
                f"Môn {subject.name} vượt giới hạn {consecutive_limit} tiết liên tiếp.",
            )
            continue

        teacher_slot_busy.add(teacher_slot_key)
        class_slot_busy.add(class_slot_key)
        teacher_day_counts[teacher_day_key] += 1
        class_subject_session_periods[subject_run_key].add(period)

    return invalid


def minimal_schedule_invalid_lessons(
    db: Session,
    project: Project,
    assignments: list[Assignment],
    lessons: list[Lesson],
) -> list[Lesson]:
    """Keep the maximum valid subset and return only truly invalid lessons."""
    return [
        lesson
        for lesson, _reason in _minimal_schedule_invalid_lesson_analysis(
            db, project, assignments, lessons
        )
    ]


def schedule_ui_validation_report(
    db: Session,
    project: Project,
) -> dict:
    """Return lightweight server-authoritative validation used by the editor UI.

    Required-double decisions stay on the backend and are validated from the
    persisted ``block_id``/``block_size`` structure. The browser never infers
    required pairs from neighboring timetable cells.
    """
    assignments = db.scalars(
        select(Assignment).where(Assignment.project_id == project.id)
    ).all()
    lessons = db.scalars(select(Lesson).where(Lesson.project_id == project.id)).all()
    fixed_rows = db.scalars(
        select(FixedLesson).where(FixedLesson.project_id == project.id)
    ).all()
    invalid_analysis = _minimal_schedule_invalid_lesson_analysis(
        db, project, assignments, lessons
    )

    lessons_by_assignment: dict[int, list[Lesson]] = defaultdict(list)
    for lesson in lessons:
        lessons_by_assignment[lesson.assignment_id].append(lesson)

    fixed_by_assignment: dict[int, list[FixedLesson]] = defaultdict(list)
    for row in fixed_rows:
        fixed_by_assignment[row.assignment_id].append(row)

    required_double_conflicts = []
    for assignment in assignments:
        if not assignment_requires_double(assignment):
            continue
        rows = lessons_by_assignment.get(assignment.id, [])
        if not rows:
            continue

        slots = [int(row.slot) for row in rows]
        block_state = required_double_block_state(project, assignment, rows)
        if block_state["valid"]:
            continue

        expected = int(assignment.periods_per_week or 0)
        actual = len(slots)
        if actual > expected:
            message = (
                f"Phân công bắt buộc tiết đôi đang có {actual}/{expected} tiết, "
                "vượt số tiết/tuần đã cấu hình."
            )
        else:
            message = "Cấu trúc block bắt buộc tiết đôi hiện không hợp lệ. " + (
                block_state.get("reason") or "Hãy tạo lại hoặc xếp lại block."
            )
        required_double_conflicts.append(
            {
                "assignment_id": assignment.id,
                "lesson_ids": [row.id for row in rows],
                "message": message,
            }
        )

    return {
        "invalid_lesson_ids": [lesson.id for lesson, _reason in invalid_analysis],
        "invalid_lesson_conflicts": [
            {"lesson_id": lesson.id, "message": reason}
            for lesson, reason in invalid_analysis
        ],
        "required_double_conflicts": required_double_conflicts,
    }


def schedule_integrity_report(
    db: Session,
    project: Project,
) -> dict:
    """Return the authoritative timetable integrity diagnostic report.

    Generation/final solver validation may still use this as a hard gate. Sharing
    and Excel export intentionally do not: users can publish/export the timetable
    in its current state and use this report separately to see remaining issues.
    """
    assignments = db.scalars(
        select(Assignment).where(Assignment.project_id == project.id)
    ).all()
    classes = db.scalars(
        select(SchoolClass).where(SchoolClass.project_id == project.id)
    ).all()
    input_report = schedule_input_validation_report(
        db, project, assignments=assignments, classes=classes
    )
    lessons = db.scalars(select(Lesson).where(Lesson.project_id == project.id)).all()

    invalid_lessons = minimal_schedule_invalid_lessons(
        db, project, assignments, lessons
    )
    by_assignment: dict[int, list[Lesson]] = defaultdict(list)
    for lesson in lessons:
        by_assignment[lesson.assignment_id].append(lesson)

    count_errors = []
    required_double_errors = []
    for assignment in assignments:
        rows = by_assignment.get(assignment.id, [])
        expected = int(assignment.periods_per_week or 0)
        actual = len(rows)
        if actual != expected:
            count_errors.append(
                {
                    "assignment_id": assignment.id,
                    "expected": expected,
                    "actual": actual,
                }
            )
            continue
        if assignment_requires_double(assignment):
            block_state = required_double_block_state(project, assignment, rows)
            if not block_state["valid"] or block_state["missing_sizes"]:
                required_double_errors.append(assignment.id)

    fixed_coverage = fixed_coverage_slots(db, project)
    fixed_errors = []
    for assignment_id, expected_slots in fixed_coverage.items():
        rows = by_assignment.get(assignment_id, [])
        actual_locked = {lesson.slot for lesson in rows if lesson.locked}
        missing_slots = sorted(expected_slots - actual_locked)
        if missing_slots:
            fixed_errors.append(
                {
                    "assignment_id": assignment_id,
                    "missing_slots": missing_slots,
                }
            )

    schedule_issue_count = (
        len(invalid_lessons)
        + len(count_errors)
        + len(required_double_errors)
        + len(fixed_errors)
    )
    issue_count = input_report["issue_count"] + schedule_issue_count
    valid = issue_count == 0

    if valid:
        message = "Thời khóa biểu hợp lệ. Bạn có thể chia sẻ hoặc xuất Excel."
    else:
        parts = []
        if input_report["assignment_reference_issues"]:
            parts.append(
                f"{len(input_report['assignment_reference_issues'])} phân công tham chiếu dữ liệu sai"
            )
        if input_report["duplicate_assignment_issues"]:
            parts.append(
                f"{len(input_report['duplicate_assignment_issues'])} lớp–môn bị phân công trùng"
            )
        if input_report["grade_requirement_issues"]:
            parts.append(
                f"{len(input_report['grade_requirement_issues'])} phân công lệch chương trình khối"
            )
        if input_report["teacher_subject_issues"]:
            parts.append(
                f"{len(input_report['teacher_subject_issues'])} phân công sai chuyên môn giáo viên"
            )
        if input_report["capacity_issues"]:
            parts.append(
                f"{len(input_report['capacity_issues'])} giáo viên vượt tải khả dụng"
            )
        if input_report["class_capacity_issues"]:
            parts.append(
                f"{len(input_report['class_capacity_issues'])} lớp vượt số ô khả dụng"
            )
        if input_report["fixed_definition_issues"]:
            parts.append(
                f"{len(input_report['fixed_definition_issues'])} dữ liệu tiết cố định không hợp lệ"
            )
        if input_report["assignment_availability_issues"]:
            parts.append(
                f"{len(input_report['assignment_availability_issues'])} phân công không đủ ô cùng khả dụng"
            )
        if invalid_lessons:
            parts.append(f"{len(invalid_lessons)} tiết vi phạm ràng buộc")
        if count_errors:
            parts.append(f"{len(count_errors)} phân công chưa đúng số tiết")
        if required_double_errors:
            parts.append(
                f"{len(required_double_errors)} phân công sai mẫu bắt buộc tiết đôi"
            )
        if fixed_errors:
            parts.append(f"{len(fixed_errors)} cụm cố định không còn toàn vẹn")
        message = (
            "Thời khóa biểu còn lỗi: "
            + ", ".join(parts)
            + ". Bạn vẫn có thể chia sẻ hoặc xuất Excel; nên kiểm tra lại các xung đột khi cần."
        )

    return {
        "ok": valid,
        "valid": valid,
        "reason": None if valid else "schedule_integrity_failed",
        "issue_count": issue_count,
        "message": message,
        "input_validation": input_report,
        "invalid_lesson_ids": [lesson.id for lesson in invalid_lessons],
        "count_errors": count_errors,
        "required_double_errors": required_double_errors,
        "fixed_errors": fixed_errors,
    }
