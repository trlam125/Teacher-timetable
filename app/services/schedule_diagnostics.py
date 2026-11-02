from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Assignment, Lesson, Project, SchoolClass, Subject, Teacher


def unscheduled_assignment_details(
    db: Session, project: Project, assignments: list[Assignment], result: dict, mode: str,
) -> list[dict]:
    """Describe the solver's trial without committing any trial lessons.

    Missing mode retains every saved row, rebuild retains only locked rows,
    and full mode starts empty. Use sets so anchored fixed periods cannot be
    counted twice when they are also present in a solver result.
    """
    current = defaultdict(set)
    trial = defaultdict(set)
    for row in db.scalars(select(Lesson).where(Lesson.project_id == project.id)).all():
        current[row.assignment_id].add(row.slot)
        if mode == "missing" or (mode == "rebuild" and row.locked):
            trial[row.assignment_id].add(row.slot)
    for assignment_id, slot, *_ in result.get("lessons", []):
        trial[assignment_id].add(slot)
    classes = {row.id: row for row in db.scalars(select(SchoolClass).where(SchoolClass.project_id == project.id))}
    subjects = {row.id: row for row in db.scalars(select(Subject).where(Subject.project_id == project.id))}
    teachers = {row.id: row for row in db.scalars(select(Teacher).where(Teacher.project_id == project.id))}
    details = []
    for assignment in assignments:
        required = int(assignment.periods_per_week or 0)
        scheduled = len(trial[assignment.id])
        if scheduled >= required:
            continue
        school_class = classes.get(assignment.class_id)
        subject = subjects.get(assignment.subject_id)
        teacher = teachers.get(assignment.teacher_id)
        details.append({
            "assignment_id": assignment.id,
            "class_id": assignment.class_id,
            "class_name": school_class.name if school_class else "?",
            "subject_id": assignment.subject_id,
            "subject_name": subject.name if subject else "?",
            "teacher_id": assignment.teacher_id,
            "teacher_name": teacher.name if teacher else "?",
            "required_periods": required,
            "scheduled_periods": scheduled,
            "current_scheduled_periods": len(current[assignment.id]),
            "missing_periods": required - scheduled,
        })
    return sorted(details, key=lambda row: (row["class_name"], row["subject_name"], row["teacher_name"]))
