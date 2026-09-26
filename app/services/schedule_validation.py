from __future__ import annotations

from app.services.foundation import *


def assignment_availability_issues(
    db: Session, project: Project, assignments: list[Assignment],
) -> list[dict]:
    """Catch legacy/impossible source assignments before invoking the solver."""
    teachers = {row.id: row for row in db.scalars(
        select(Teacher).where(Teacher.project_id == project.id)
    ).all()}
    classes = {row.id: row for row in db.scalars(
        select(SchoolClass).where(SchoolClass.project_id == project.id)
    ).all()}
    subjects = {row.id: row for row in db.scalars(
        select(Subject).where(Subject.project_id == project.id)
    ).all()}
    issues = []
    for assignment in assignments:
        teacher = teachers.get(assignment.teacher_id)
        school_class = classes.get(assignment.class_id)
        subject = subjects.get(assignment.subject_id)
        if not teacher or not school_class or not subject:
            continue  # Reported by the reference validator.
        try:
            ensure_assignment_hard_feasible(
                project, teacher, school_class, subject,
                assignment.periods_per_week, assignment.block_mode,
            )
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            issues.append({"assignment_id": assignment.id, "message": str(exc.detail)})
    return issues


def teacher_subject_assignment_issues(
    db: Session,
    project: Project,
    assignments: list[Assignment],
) -> list[dict]:
    """Return assignments whose teacher is not configured for the subject."""
    if not assignments:
        return []

    teacher_ids = {row.teacher_id for row in assignments}
    subject_ids = {row.subject_id for row in assignments}
    allowed = set(
        db.execute(
            select(TeacherSubject.teacher_id, TeacherSubject.subject_id).where(
                TeacherSubject.project_id == project.id,
                TeacherSubject.teacher_id.in_(teacher_ids),
                TeacherSubject.subject_id.in_(subject_ids),
            )
        ).all()
    )

    teachers = {
        row.id: row
        for row in db.scalars(
            select(Teacher).where(
                Teacher.project_id == project.id,
                Teacher.id.in_(teacher_ids),
            )
        ).all()
    }
    subjects = {
        row.id: row
        for row in db.scalars(
            select(Subject).where(
                Subject.project_id == project.id,
                Subject.id.in_(subject_ids),
            )
        ).all()
    }

    issues = []
    for assignment in assignments:
        # Missing/cross-project references are reported separately by the
        # project-reference validator; do not duplicate the same problem here.
        teacher = teachers.get(assignment.teacher_id)
        subject = subjects.get(assignment.subject_id)
        if not teacher or not subject:
            continue
        if (assignment.teacher_id, assignment.subject_id) in allowed:
            continue
        issues.append(
            {
                "assignment_id": assignment.id,
                "teacher_id": teacher.id,
                "teacher_name": teacher.name,
                "subject_id": subject.id,
                "subject_name": subject.name,
            }
        )
    return issues


def fixed_lesson_definition_issues(
    db: Session,
    project: Project,
    assignments: list[Assignment],
) -> list[dict]:
    """Validate FixedLesson metadata without mutating legacy data.

    Coverage is checked later against actual Lesson rows. This function only
    verifies that every persisted fixed row has a valid owner, size and group
    layout for the current assignment mode/project dimensions.
    """
    assignment_by_id = {row.id: row for row in assignments}
    rows = db.scalars(
        select(FixedLesson).where(FixedLesson.project_id == project.id)
    ).all()
    if not rows:
        return []

    specs_by_assignment: dict[int, list[tuple[int, int]]] = defaultdict(list)
    issues: list[dict] = []
    invalid_assignment_ids: set[int] = set()

    for row in rows:
        assignment = assignment_by_id.get(row.assignment_id)
        if not assignment:
            # Generate already removes legacy orphan rows transactionally. Do not
            # turn that repairable legacy state into a new hard blocker here.
            continue

        try:
            persisted_size = int(row.group_size)
        except (TypeError, ValueError, OverflowError):
            persisted_size = 0
        allowed_sizes = set(assignment_groups(assignment))
        if persisted_size < 1 or persisted_size not in allowed_sizes:
            invalid_assignment_ids.add(assignment.id)
            issues.append(
                {
                    "fixed_lesson_id": row.id,
                    "assignment_id": assignment.id,
                    "slot": row.slot,
                    "group_size": row.group_size,
                    "issue_type": "invalid_group_size",
                    "message": (
                        "Kích thước cụm cố định không phù hợp chế độ xếp tiết hiện tại."
                    ),
                }
            )
            continue
        specs_by_assignment[assignment.id].append((row.slot, persisted_size))

    for assignment_id, specs in specs_by_assignment.items():
        if assignment_id in invalid_assignment_ids:
            continue
        assignment = assignment_by_id[assignment_id]
        error = fixed_group_validation_error(
            assignment_groups(assignment),
            specs,
            days=project.days,
            sessions=project.sessions,
            periods_per_session=project.periods_per_session,
        )
        if error:
            issues.append(
                {
                    "assignment_id": assignment_id,
                    "issue_type": "invalid_group_layout",
                    "message": error,
                }
            )

    return issues


def schedule_input_validation_report(
    db: Session,
    project: Project,
    assignments: list[Assignment] | None = None,
    classes: list[SchoolClass] | None = None,
) -> dict:
    """Single non-mutating validation gate for timetable source data.

    Generate, final integrity validation, share and export all consume this
    report so they cannot disagree about whether the underlying project data is
    fit for scheduling/publishing.
    """
    # Imported lazily to avoid the existing entities -> schedule_service import
    # dependency during module initialization.
    from app.services.entities import (
        assignment_project_reference_issues,
        duplicate_assignment_issues,
        grade_requirement_assignment_issues,
        schedule_class_capacity_issues,
        schedule_teacher_capacity_issues,
    )

    if assignments is None:
        assignments = db.scalars(
            select(Assignment).where(Assignment.project_id == project.id)
        ).all()
    if classes is None:
        classes = db.scalars(
            select(SchoolClass).where(SchoolClass.project_id == project.id)
        ).all()

    reference_issues = assignment_project_reference_issues(
        db, project.id, assignments
    )
    duplicate_issues = duplicate_assignment_issues(db, assignments)
    curriculum_issues = grade_requirement_assignment_issues(
        db, project, assignments, classes
    )
    teacher_subject_issues = teacher_subject_assignment_issues(
        db, project, assignments
    )
    teacher_capacity_issues = schedule_teacher_capacity_issues(
        db, project, assignments
    )
    class_capacity_issues = schedule_class_capacity_issues(
        project, classes, assignments
    )
    fixed_definition_issues = fixed_lesson_definition_issues(
        db, project, assignments
    )
    availability_issues = assignment_availability_issues(db, project, assignments)

    issue_count = sum(
        len(items)
        for items in (
            reference_issues,
            duplicate_issues,
            curriculum_issues,
            teacher_subject_issues,
            teacher_capacity_issues,
            class_capacity_issues,
            fixed_definition_issues,
            availability_issues,
        )
    )
    valid = issue_count == 0
    return {
        "ok": valid,
        "valid": valid,
        "reason": None if valid else "schedule_input_invalid",
        "issue_count": issue_count,
        "assignment_reference_issues": reference_issues,
        "duplicate_assignment_issues": duplicate_issues,
        "grade_requirement_issues": curriculum_issues,
        "teacher_subject_issues": teacher_subject_issues,
        "capacity_issues": teacher_capacity_issues,
        "class_capacity_issues": class_capacity_issues,
        "fixed_definition_issues": fixed_definition_issues,
        "assignment_availability_issues": availability_issues,
    }
