from __future__ import annotations

from app.models import Assignment, GradeSubjectRequirement, Project, SchoolClass, Subject
from app.services.entities.curriculum.validation import block_mode_text
from sqlalchemy import select
from sqlalchemy.orm import Session


def grade_requirement_extra_assignments(
    db: Session,
    project: Project,
    grade_id: int,
    classes: list[SchoolClass] | None = None,
    configs: list[tuple[int, int, str]] | None = None,
) -> list[dict]:
    """Return assignments whose subjects are outside a configured target grade.

    ``configs`` can be supplied while editing a grade so the comparison is made
    against the proposed curriculum instead of the rows currently persisted in
    the database. An empty target curriculum is treated as not configured, so it
    does not make existing assignments extra.
    """
    if configs is None:
        requirements = db.scalars(
            select(GradeSubjectRequirement).where(
                GradeSubjectRequirement.project_id == project.id,
                GradeSubjectRequirement.grade_id == grade_id,
            )
        ).all()
        if not requirements:
            return []
        wanted_subject_ids = {row.subject_id for row in requirements}
    else:
        if not configs:
            return []
        wanted_subject_ids = {subject_id for subject_id, _, _ in configs}

    if classes is None:
        classes = db.scalars(
            select(SchoolClass).where(
                SchoolClass.project_id == project.id,
                SchoolClass.grade_id == grade_id,
            )
        ).all()
    if not classes:
        return []

    class_by_id = {row.id: row for row in classes}
    assignments = db.scalars(
        select(Assignment).where(
            Assignment.project_id == project.id,
            Assignment.class_id.in_(list(class_by_id)),
        )
    ).all()
    extras = [row for row in assignments if row.subject_id not in wanted_subject_ids]
    if not extras:
        return []
    subject_ids = {row.subject_id for row in extras}
    subjects = {
        row.id: row
        for row in db.scalars(
            select(Subject).where(
                Subject.project_id == project.id,
                Subject.id.in_(subject_ids),
            )
        ).all()
    }
    return [
        {
            "assignment_id": row.id,
            "class_id": row.class_id,
            "class_name": class_by_id[row.class_id].name,
            "subject_id": row.subject_id,
            "subject_name": subjects.get(row.subject_id).name
            if subjects.get(row.subject_id)
            else f"môn #{row.subject_id}",
            "assigned_periods": int(row.periods_per_week),
            "assigned_mode": row.block_mode or "free",
        }
        for row in extras
    ]


def grade_requirement_missing_assignments(
    db: Session,
    project: Project,
    grade_id: int,
    configs: list[tuple[int, int, str]],
    classes: list[SchoolClass] | None = None,
) -> list[str]:
    """Trả về các môn bắt buộc chưa có phân công cho từng lớp.

    Các phân công đã tồn tại nhưng khác số tiết/chế độ sẽ được đồng bộ nguyên tử
    bởi ``sync_assignments_to_grade_requirements``. Chỉ trường hợp chưa có
    phân công mới cần người dùng chọn giáo viên trước.
    """
    if classes is None:
        classes = db.scalars(
            select(SchoolClass).where(
                SchoolClass.project_id == project.id,
                SchoolClass.grade_id == grade_id,
            )
        ).all()
    if not classes or not configs:
        return []
    class_ids = [row.id for row in classes]
    subject_ids = [subject_id for subject_id, _, _ in configs]
    assignments = db.scalars(
        select(Assignment).where(
            Assignment.project_id == project.id,
            Assignment.class_id.in_(class_ids),
            Assignment.subject_id.in_(subject_ids),
        )
    ).all()
    assigned_pairs = {(row.class_id, row.subject_id) for row in assignments}
    subjects = {
        row.id: row
        for row in db.scalars(
            select(Subject).where(
                Subject.project_id == project.id,
                Subject.id.in_(subject_ids),
            )
        ).all()
    }
    issues: list[str] = []
    for school_class in classes:
        for subject_id, required_periods, required_mode in configs:
            if (school_class.id, subject_id) in assigned_pairs:
                continue
            subject = subjects.get(subject_id)
            subject_name = subject.name if subject else f"môn #{subject_id}"
            issues.append(
                f"{school_class.name} – {subject_name}: thiếu phân công "
                f"{required_periods} tiết/tuần · {block_mode_text(required_mode)}"
            )
    return issues
