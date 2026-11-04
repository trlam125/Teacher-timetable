from __future__ import annotations

from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Assignment,
    Grade,
    GradeSubjectRequirement,
    Project,
    SchoolClass,
    Subject,
    Teacher,
    TeacherSubject,
)
from app.scheduling.rules import (
    all_slots,
    bounded_int,
    class_blocked_slots,
    normalized_block_mode,
    parse_slots,
    valid_slots,
)


def required_id(data: dict, key: str, label: str) -> int:
    value = data.get(key)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"{label} không hợp lệ") from exc
    if parsed <= 0:
        raise HTTPException(400, f"{label} không hợp lệ")
    return parsed


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


def ensure_grade_program_fits(
    project: Project, grade: Grade | None, total_periods: int, *,
    project_blocked_slots: set[int] | None = None,
    grade_blocked_slots: set[int] | None = None,
) -> None:
    blocked = set(parse_slots(project.blocked_slots_json) if project_blocked_slots is None else project_blocked_slots)
    blocked.update(
        parse_slots(grade.blocked_slots_json) if grade is not None and grade_blocked_slots is None
        else grade_blocked_slots or set()
    )
    capacity = len(set(all_slots(project)) - blocked)
    if total_periods > capacity:
        label = grade.name if grade is not None else "khối"
        raise HTTPException(409,
            f"Chương trình {label} cần {total_periods} tiết/tuần nhưng chỉ còn {capacity} ô "
            "sau khi trừ khóa toàn trường và khóa khối. Hãy điều chỉnh chương trình hoặc khóa lịch.")


def normalized_grade_requirements(
    db: Session, project: Project, values, grade_id: int | None = None,
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

    grade = db.get(Grade, grade_id) if grade_id is not None else None
    if grade_id is not None and (grade is None or grade.project_id != project.id):
        raise HTTPException(404, "Không tìm thấy khối lớp")
    ensure_grade_program_fits(project, grade, sum(periods for periods, _ in configs.values()))

    return [
        (subject_id, periods, mode) for subject_id, (periods, mode) in configs.items()
    ]


def replace_grade_requirements(
    db: Session, project: Project, grade_id: int, values
) -> None:
    configs = normalized_grade_requirements(db, project, values, grade_id=grade_id)
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
        class_blocked_slots(school_class)
        if unavailable_slots is None
        else unavailable_slots
    )
    class_blocked = set(valid_slots(project, class_blocked, strict=False))
    return maximum - len(project_blocked | class_blocked)


def class_assigned_periods(db: Session, project_id: int, class_id: int) -> int:
    value = db.scalar(
        select(func.coalesce(func.sum(Assignment.periods_per_week), 0)).where(
            Assignment.project_id == project_id,
            Assignment.class_id == class_id,
        )
    )
    return int(value or 0)


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
