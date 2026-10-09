from __future__ import annotations

from app.models import (
    Assignment,
    Grade,
    GradeSubjectRequirement,
    Project,
    SchoolClass,
    Subject,
)
from collections import defaultdict
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session


def grade_requirement_assignment_issues(
    db: Session,
    project: Project,
    assignments: list[Assignment] | None = None,
    classes: list[SchoolClass] | None = None,
) -> list[dict]:
    """Return missing, mismatched and extra assignments for configured curricula.

    A grade is treated as having a strict curriculum only when it has at least one
    ``GradeSubjectRequirement`` row. Grades without any configured requirement keep
    the legacy/open behaviour, so their assignments are not reported as ``extra``.
    """
    requirements = db.scalars(
        select(GradeSubjectRequirement).where(
            GradeSubjectRequirement.project_id == project.id,
        )
    ).all()
    if not requirements:
        return []
    if assignments is None:
        assignments = db.scalars(
            select(Assignment).where(Assignment.project_id == project.id)
        ).all()
    if classes is None:
        classes = db.scalars(
            select(SchoolClass).where(SchoolClass.project_id == project.id)
        ).all()

    requirement_by_grade = defaultdict(list)
    required_subject_ids_by_grade = defaultdict(set)
    for requirement in requirements:
        requirement_by_grade[requirement.grade_id].append(requirement)
        required_subject_ids_by_grade[requirement.grade_id].add(requirement.subject_id)

    assignment_by_pair = {(row.class_id, row.subject_id): row for row in assignments}
    assignments_by_class = defaultdict(list)
    for assignment in assignments:
        assignments_by_class[assignment.class_id].append(assignment)

    subject_ids = {row.subject_id for row in requirements}
    subject_ids.update(row.subject_id for row in assignments)
    subjects = (
        {
            row.id: row
            for row in db.scalars(
                select(Subject).where(
                    Subject.project_id == project.id,
                    Subject.id.in_(subject_ids),
                )
            ).all()
        }
        if subject_ids
        else {}
    )
    grade_ids = {row.grade_id for row in requirements}
    grades = (
        {
            row.id: row
            for row in db.scalars(
                select(Grade).where(
                    Grade.project_id == project.id,
                    Grade.id.in_(grade_ids),
                )
            ).all()
        }
        if grade_ids
        else {}
    )

    issues: list[dict] = []
    for school_class in classes:
        if school_class.grade_id is None:
            continue
        grade_requirements = requirement_by_grade.get(school_class.grade_id, [])
        if not grade_requirements:
            # No configured curriculum for this grade: assignments remain open-ended.
            continue
        grade = grades.get(school_class.grade_id)
        required_subject_ids = required_subject_ids_by_grade[school_class.grade_id]

        for requirement in grade_requirements:
            assignment = assignment_by_pair.get(
                (school_class.id, requirement.subject_id)
            )
            subject = subjects.get(requirement.subject_id)
            base = {
                "class_id": school_class.id,
                "class_name": school_class.name,
                "grade_id": school_class.grade_id,
                "grade_name": grade.name if grade else "?",
                "subject_id": requirement.subject_id,
                "subject_name": subject.name if subject else "?",
                "required_periods": int(requirement.periods_per_week),
                "required_mode": requirement.block_mode or "free",
            }
            if assignment is None:
                issues.append({**base, "issue_type": "missing"})
                continue
            actual_periods = int(assignment.periods_per_week)
            actual_mode = assignment.block_mode or "free"
            if actual_periods != int(requirement.periods_per_week) or actual_mode != (
                requirement.block_mode or "free"
            ):
                issues.append(
                    {
                        **base,
                        "issue_type": "mismatch",
                        "assignment_id": assignment.id,
                        "assigned_periods": actual_periods,
                        "assigned_mode": actual_mode,
                    }
                )

        for assignment in assignments_by_class.get(school_class.id, []):
            if assignment.subject_id in required_subject_ids:
                continue
            subject = subjects.get(assignment.subject_id)
            issues.append(
                {
                    "issue_type": "extra",
                    "assignment_id": assignment.id,
                    "class_id": school_class.id,
                    "class_name": school_class.name,
                    "grade_id": school_class.grade_id,
                    "grade_name": grade.name if grade else "?",
                    "subject_id": assignment.subject_id,
                    "subject_name": subject.name if subject else "?",
                    "assigned_periods": int(assignment.periods_per_week),
                    "assigned_mode": assignment.block_mode or "free",
                }
            )

    issue_order = {"missing": 0, "mismatch": 1, "extra": 2}
    issues.sort(
        key=lambda item: (
            item["class_name"],
            item["subject_name"],
            issue_order.get(item["issue_type"], 99),
        )
    )
    return issues


def block_mode_text(mode: str) -> str:
    return {
        "free": "Tự do",
        "preferred_double": "Ưu tiên tiết đôi",
        "required_double": "Bắt buộc tiết đôi",
    }.get(mode or "free", mode or "Tự do")


def grade_requirement_for_assignment(
    db: Session,
    project_id: int,
    school_class: SchoolClass,
    subject_id: int,
) -> GradeSubjectRequirement | None:
    if school_class.grade_id is None:
        return None
    return db.scalar(
        select(GradeSubjectRequirement).where(
            GradeSubjectRequirement.project_id == project_id,
            GradeSubjectRequirement.grade_id == school_class.grade_id,
            GradeSubjectRequirement.subject_id == subject_id,
        )
    )


def ensure_assignment_matches_grade_requirement(
    db: Session,
    project: Project,
    school_class: SchoolClass,
    subject: Subject,
    periods: int,
    mode: str,
) -> None:
    requirement = grade_requirement_for_assignment(
        db, project.id, school_class, subject.id
    )
    if requirement is None:
        if school_class.grade_id is None:
            return
        grade_has_program = db.scalar(
            select(GradeSubjectRequirement.id).where(
                GradeSubjectRequirement.project_id == project.id,
                GradeSubjectRequirement.grade_id == school_class.grade_id,
            )
        )
        if grade_has_program is None:
            # A grade with no configured curriculum remains open-ended.
            return
        grade = db.get(Grade, school_class.grade_id)
        raise HTTPException(
            409,
            f"{school_class.name} – {subject.name} không thuộc chương trình "
            f"{grade.name if grade else 'khối'} đã cấu hình. "
            "Hãy thêm môn vào chương trình khối hoặc chọn môn khác.",
        )
    required_periods = int(requirement.periods_per_week)
    required_mode = requirement.block_mode or "free"
    if periods == required_periods and mode == required_mode:
        return
    grade = db.get(Grade, school_class.grade_id) if school_class.grade_id else None
    raise HTTPException(
        409,
        f"{school_class.name} – {subject.name} phải khớp chương trình "
        f"{grade.name if grade else 'khối'}: {required_periods} tiết/tuần · "
        f"{block_mode_text(required_mode)}. Dữ liệu đang nhập là "
        f"{periods} tiết/tuần · {block_mode_text(mode)}.",
    )
