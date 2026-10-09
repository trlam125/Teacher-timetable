from __future__ import annotations

from app.models import Assignment, Project, SchoolClass, Subject, Teacher
from app.scheduling.rules import parse_slots, valid_slots
from app.services.entities.validation import class_week_capacity, teacher_week_capacity
from collections import Counter
from sqlalchemy import select
from sqlalchemy.orm import Session


def assignment_project_reference_issues(
    db: Session, project_id: int, assignments: list[Assignment]
) -> list[dict]:
    """Phát hiện phân công tham chiếu lớp/môn/GV mất hoặc thuộc project khác."""
    if not assignments:
        return []
    teacher_ids = {row.teacher_id for row in assignments}
    class_ids = {row.class_id for row in assignments}
    subject_ids = {row.subject_id for row in assignments}
    teacher_projects = (
        dict(
            db.execute(
                select(Teacher.id, Teacher.project_id).where(
                    Teacher.id.in_(teacher_ids)
                )
            ).all()
        )
        if teacher_ids
        else {}
    )
    class_projects = (
        dict(
            db.execute(
                select(SchoolClass.id, SchoolClass.project_id).where(
                    SchoolClass.id.in_(class_ids)
                )
            ).all()
        )
        if class_ids
        else {}
    )
    subject_projects = (
        dict(
            db.execute(
                select(Subject.id, Subject.project_id).where(
                    Subject.id.in_(subject_ids)
                )
            ).all()
        )
        if subject_ids
        else {}
    )

    specs = (
        ("teacher_id", "Giáo viên", teacher_projects),
        ("class_id", "Lớp", class_projects),
        ("subject_id", "Môn", subject_projects),
    )
    issues = []
    for assignment in assignments:
        invalid_refs = []
        for field, label, projects_by_id in specs:
            reference_id = getattr(assignment, field)
            actual_project_id = projects_by_id.get(reference_id)
            if actual_project_id != project_id:
                invalid_refs.append(
                    {
                        "field": field,
                        "label": label,
                        "id": reference_id,
                        "actual_project_id": actual_project_id,
                    }
                )
        if invalid_refs:
            issues.append(
                {
                    "assignment_id": assignment.id,
                    "invalid_refs": invalid_refs,
                }
            )
    return issues


def schedule_teacher_capacity_issues(
    db: Session,
    project: Project,
    assignments: list[Assignment],
) -> list[dict]:
    """Return teacher loads that cannot fit even before conflict solving.

    This necessary (but not sufficient) feasibility check also covers legacy
    and imported data that predates assignment-time load validation. It lets the
    scheduler explain the real constraint instead of appearing to skip teachers.
    """
    assigned_by_teacher = Counter()
    for assignment in assignments:
        assigned_by_teacher[assignment.teacher_id] += int(
            assignment.periods_per_week or 0
        )

    project_blocked = set(
        valid_slots(
            project,
            parse_slots(project.blocked_slots_json),
            strict=False,
        )
    )
    issues = []
    for teacher_id, assigned in assigned_by_teacher.items():
        teacher = db.get(Teacher, teacher_id)
        if not teacher:
            continue
        capacity = teacher_week_capacity(
            project,
            teacher,
            project_blocked_slots=project_blocked,
        )
        if assigned > capacity:
            issues.append(
                {
                    "teacher_id": teacher.id,
                    "teacher_name": teacher.name,
                    "assigned": assigned,
                    "capacity": capacity,
                    "excess": assigned - capacity,
                }
            )
    return sorted(issues, key=lambda item: (-item["excess"], item["teacher_name"]))


def schedule_class_capacity_issues(
    project: Project,
    classes: list[SchoolClass],
    assignments: list[Assignment],
) -> list[dict]:
    assigned_by_class = Counter()
    for assignment in assignments:
        assigned_by_class[assignment.class_id] += int(assignment.periods_per_week or 0)
    issues = []
    for school_class in classes:
        assigned = assigned_by_class[school_class.id]
        if not assigned:
            continue
        capacity = class_week_capacity(project, school_class)
        if assigned > capacity:
            issues.append(
                {
                    "class_id": school_class.id,
                    "class_name": school_class.name,
                    "assigned": assigned,
                    "capacity": capacity,
                    "excess": assigned - capacity,
                }
            )
    return sorted(issues, key=lambda item: (-item["excess"], item["class_name"]))
