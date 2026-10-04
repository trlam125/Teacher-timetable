from __future__ import annotations

from app.services.foundation import *
from app.services.web import *
from app.services.schedule_service import *


def ensure_unique_project_name(
    db: Session,
    model,
    project_id: int,
    name: str,
    label: str,
    exclude_id: int | None = None,
) -> None:
    stmt = select(model.id).where(
        model.project_id == project_id,
        func.lower(model.name) == name.lower(),
    )
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise HTTPException(409, f"{label} ‘{name}’ đã tồn tại trong bộ thời khóa biểu")


def ensure_unique_teacher_short_name(
    db: Session,
    project_id: int,
    short_name: str,
    exclude_id: int | None = None,
) -> None:
    normalized = short_name.strip()
    stmt = select(Teacher.id).where(
        Teacher.project_id == project_id,
        func.lower(func.trim(Teacher.short_name)) == normalized.lower(),
    )
    if exclude_id is not None:
        stmt = stmt.where(Teacher.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise HTTPException(
            409,
            f"Tên ngắn giáo viên ‘{normalized}’ đã được sử dụng trong bộ thời khóa biểu",
        )


def validated_subject_ids(db: Session, project_id: int, values) -> list[int]:
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]
    result = []
    for value in values:
        try:
            subject_id = int(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                400, "Danh sách môn của giáo viên không hợp lệ"
            ) from exc
        if subject_id > 0 and subject_id not in result:
            result.append(subject_id)
    if not result:
        return []
    found = set(
        db.scalars(
            select(Subject.id).where(
                Subject.project_id == project_id,
                Subject.id.in_(result),
            )
        ).all()
    )
    if found != set(result):
        raise HTTPException(400, "Có môn học không thuộc bộ thời khóa biểu")
    return result


def replace_teacher_subjects(
    db: Session, project_id: int, teacher_id: int, subject_ids: list[int]
) -> None:
    rows = db.scalars(
        select(TeacherSubject).where(
            TeacherSubject.project_id == project_id,
            TeacherSubject.teacher_id == teacher_id,
        )
    ).all()
    existing = {row.subject_id: row for row in rows}
    wanted = set(subject_ids)
    for subject_id, row in existing.items():
        if subject_id not in wanted:
            db.delete(row)
    for subject_id in subject_ids:
        if subject_id not in existing:
            db.add(
                TeacherSubject(
                    project_id=project_id, teacher_id=teacher_id, subject_id=subject_id
                )
            )


def normalized_grade_requirements(
    db: Session, project: Project, values
) -> list[tuple[int, int, str]]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise HTTPException(400, "Chương trình môn của khối không hợp lệ")
    configs: dict[int, tuple[int, str]] = {}
    for item in values:
        if not isinstance(item, dict):
            raise HTTPException(400, "Chương trình môn của khối không hợp lệ")
        subject_id = required_id(item, "subject_id", "Môn học")
        subject = db.get(Subject, subject_id)
        if not subject or subject.project_id != project.id:
            raise HTTPException(400, "Có môn học không thuộc bộ thời khóa biểu")
        periods = bounded_int(
            item.get("periods_per_week"), 1, 1, 40, f"Số tiết/tuần của {subject.name}"
        )
        try:
            mode = normalized_block_mode(
                item.get("block_mode", "free"), periods, subject, project
            )
        except ValueError as exc:
            raise HTTPException(400, f"{subject.name}: {exc}") from exc
        configs[subject_id] = (periods, mode)

    blocked_slots = set(
        valid_slots(
            project,
            parse_slots(project.blocked_slots_json),
            strict=False,
        )
    )
    weekly_capacity = max(
        0,
        project.days * project.sessions * project.periods_per_session
        - len(blocked_slots),
    )
    total_periods = sum(periods for periods, _ in configs.values())
    if total_periods > weekly_capacity:
        raise HTTPException(
            409,
            f"Tổng chương trình khối là {total_periods} tiết/tuần, vượt sức chứa "
            f"tối đa {weekly_capacity} tiết/tuần của thời khóa biểu hiện tại "
            f"(đã trừ {len(blocked_slots)} ô khóa toàn cục).",
        )

    return [
        (subject_id, periods, mode) for subject_id, (periods, mode) in configs.items()
    ]


def replace_grade_requirements(
    db: Session, project: Project, grade_id: int, values
) -> None:
    configs = normalized_grade_requirements(db, project, values)
    rows = db.scalars(
        select(GradeSubjectRequirement).where(
            GradeSubjectRequirement.project_id == project.id,
            GradeSubjectRequirement.grade_id == grade_id,
        )
    ).all()
    existing = {row.subject_id: row for row in rows}
    wanted = {subject_id for subject_id, _, _ in configs}
    for subject_id, row in existing.items():
        if subject_id not in wanted:
            db.delete(row)
    for subject_id, periods, mode in configs:
        row = existing.get(subject_id)
        if row is None:
            db.add(
                GradeSubjectRequirement(
                    project_id=project.id,
                    grade_id=grade_id,
                    subject_id=subject_id,
                    periods_per_week=periods,
                    block_mode=mode,
                )
            )
        else:
            row.periods_per_week = periods
            row.block_mode = mode


def teacher_week_capacity(
    project: Project,
    teacher: Teacher,
    max_periods_day: int | None = None,
    unavailable_slots: set[int] | None = None,
    project_blocked_slots: set[int] | None = None,
) -> int:
    daily_limit = (
        max_periods_day if max_periods_day is not None else teacher.max_periods_day
    )
    periods_per_day = project.sessions * project.periods_per_session
    project_blocked = (
        project_blocked_slots
        if project_blocked_slots is not None
        else set(
            valid_slots(
                project,
                parse_slots(project.blocked_slots_json),
                strict=False,
            )
        )
    )
    teacher_blocked = (
        parse_slots(teacher.unavailable_json)
        if unavailable_slots is None
        else set(unavailable_slots)
    )
    teacher_blocked = set(valid_slots(project, teacher_blocked, strict=False))
    capacity = 0
    for day in range(project.days):
        start = day * periods_per_day
        available = sum(
            1
            for slot in range(start, start + periods_per_day)
            if slot not in project_blocked and slot not in teacher_blocked
        )
        capacity += min(daily_limit, available)
    return capacity


def class_week_capacity(
    project: Project,
    school_class: SchoolClass,
    unavailable_slots: set[int] | None = None,
    project_blocked_slots: set[int] | None = None,
) -> int:
    maximum = project.days * project.sessions * project.periods_per_session
    project_blocked = (
        project_blocked_slots
        if project_blocked_slots is not None
        else set(
            valid_slots(
                project,
                parse_slots(project.blocked_slots_json),
                strict=False,
            )
        )
    )
    class_blocked = (
        parse_slots(school_class.unavailable_json)
        if unavailable_slots is None
        else unavailable_slots
    )
    class_blocked = set(valid_slots(project, class_blocked, strict=False))
    return maximum - len(project_blocked | class_blocked)


def teacher_assigned_periods(db: Session, project_id: int, teacher_id: int) -> int:
    value = db.scalar(
        select(func.coalesce(func.sum(Assignment.periods_per_week), 0)).where(
            Assignment.project_id == project_id,
            Assignment.teacher_id == teacher_id,
        )
    )
    return int(value or 0)


def class_assigned_periods(db: Session, project_id: int, class_id: int) -> int:
    value = db.scalar(
        select(func.coalesce(func.sum(Assignment.periods_per_week), 0)).where(
            Assignment.project_id == project_id,
            Assignment.class_id == class_id,
        )
    )
    return int(value or 0)


def ensure_teacher_load_fits(
    db: Session,
    project: Project,
    teacher: Teacher,
    projected_periods: int,
    max_periods_day: int | None = None,
    unavailable_slots: set[int] | None = None,
    project_blocked_slots: set[int] | None = None,
) -> None:
    capacity = teacher_week_capacity(
        project,
        teacher,
        max_periods_day=max_periods_day,
        unavailable_slots=unavailable_slots,
        project_blocked_slots=project_blocked_slots,
    )
    if projected_periods > capacity:
        raise HTTPException(
            409,
            f"Tải dạy của {teacher.name} sẽ là {projected_periods} tiết/tuần, "
            f"vượt khả năng tối đa hiện tại {capacity} tiết/tuần theo số ngày, "
            "tiết tránh và giới hạn tiết/ngày.",
        )


def ensure_class_load_fits(
    project: Project,
    school_class: SchoolClass,
    projected_periods: int,
    unavailable_slots: set[int] | None = None,
    project_blocked_slots: set[int] | None = None,
) -> None:
    capacity = class_week_capacity(
        project,
        school_class,
        unavailable_slots=unavailable_slots,
        project_blocked_slots=project_blocked_slots,
    )
    if projected_periods > capacity:
        raise HTTPException(
            409,
            f"Tải học của lớp {school_class.name} sẽ là {projected_periods} tiết/tuần, "
            f"vượt {capacity} ô có thể học theo khóa lịch và tiết tránh hiện tại.",
        )


def duplicate_assignment_issues(
    db: Session, assignments: list[Assignment]
) -> list[dict]:
    grouped = defaultdict(list)
    for assignment in assignments:
        grouped[(assignment.class_id, assignment.subject_id)].append(assignment)
    issues = []
    for (class_id, subject_id), rows in grouped.items():
        if len(rows) < 2:
            continue
        school_class = db.get(SchoolClass, class_id)
        subject = db.get(Subject, subject_id)
        teacher_names = []
        for row in rows:
            teacher = db.get(Teacher, row.teacher_id)
            teacher_names.append(
                teacher.name if teacher else f"Giáo viên #{row.teacher_id}"
            )
        issues.append(
            {
                "class_id": class_id,
                "class_name": school_class.name if school_class else f"Lớp #{class_id}",
                "subject_id": subject_id,
                "subject_name": subject.name if subject else f"Môn #{subject_id}",
                "assignment_ids": sorted(row.id for row in rows),
                "teacher_names": teacher_names,
            }
        )
    return sorted(issues, key=lambda item: (item["class_name"], item["subject_name"]))


__all__ = [name for name in globals() if not name.startswith("__")]
