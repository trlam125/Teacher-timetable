from __future__ import annotations

from app.services.foundation import *
from app.services.web import *
from app.services.schedule_service import *

from .validation import *
from .requirements import *


def required_text(data: dict, key: str, label: str, max_length: int) -> str:
    return bounded_text(data.get(key, ""), label, max_length)


def required_id(data: dict, key: str, label: str) -> int:
    value = data.get(key)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"{label} không hợp lệ") from exc
    if parsed <= 0:
        raise HTTPException(400, f"{label} không hợp lệ")
    return parsed


def schedule_displacement_confirmation(
    db: Session,
    displaced_lesson_ids: list[int],
    *,
    confirmed: bool,
    confirmed_ids: list[int] | None,
):
    """Require approval of the exact rows removed; rollback every preview write."""
    affected = sorted(set(displaced_lesson_ids))
    if not affected or (confirmed is True and confirmed_ids == affected):
        return None
    db.rollback()
    return JSONResponse(
        {
            "ok": False,
            "reason": "schedule_displacement",
            "requires_confirmation": True,
            "affected_lessons": len(affected),
            "affected_lesson_ids": affected,
            "message": (
                f"Thay đổi này sẽ gỡ {len(affected)} tiết khỏi thời khóa biểu. "
                "Phần còn thiếu theo số tiết mới sẽ xuất hiện trong khay để xếp lại. "
                "Các tiết cố định được giữ nguyên. Bạn có muốn tiếp tục không?"
            ),
        },
        409,
    )


def entity_delete_dependency(db: Session, typ: str, eid: int):
    # Use explicit branches so deleting one entity does not execute dependency
    # queries for every other entity type.
    if typ == "department":
        return db.scalar(select(Teacher.id).where(Teacher.department_id == eid))
    if typ == "subject":
        dependency = db.scalar(
            select(Assignment.id).where(Assignment.subject_id == eid)
        )
        if dependency is not None:
            return dependency
        return db.scalar(
            select(GradeSubjectRequirement.id).where(
                GradeSubjectRequirement.subject_id == eid
            )
        )
    if typ == "teacher":
        return db.scalar(select(Assignment.id).where(Assignment.teacher_id == eid))
    if typ == "grade":
        return db.scalar(select(SchoolClass.id).where(SchoolClass.grade_id == eid))
    if typ == "class":
        return db.scalar(select(Assignment.id).where(Assignment.class_id == eid))
    return None


def entity_delete_dependency_ids(db: Session, typ: str, ids: list[int]) -> set[int]:
    """Return selected entity IDs that are still referenced, in batch."""
    wanted = {int(value) for value in ids}
    if not wanted or typ == "assignment":
        return set()
    if typ == "department":
        return set(
            db.scalars(
                select(Teacher.department_id).where(Teacher.department_id.in_(wanted))
            ).all()
        )
    if typ == "subject":
        assigned = set(
            db.scalars(
                select(Assignment.subject_id).where(Assignment.subject_id.in_(wanted))
            ).all()
        )
        required = set(
            db.scalars(
                select(GradeSubjectRequirement.subject_id).where(
                    GradeSubjectRequirement.subject_id.in_(wanted)
                )
            ).all()
        )
        return assigned | required
    if typ == "teacher":
        return set(
            db.scalars(
                select(Assignment.teacher_id).where(Assignment.teacher_id.in_(wanted))
            ).all()
        )
    if typ == "grade":
        return set(
            db.scalars(
                select(SchoolClass.grade_id).where(SchoolClass.grade_id.in_(wanted))
            ).all()
        )
    if typ == "class":
        return set(
            db.scalars(
                select(Assignment.class_id).where(Assignment.class_id.in_(wanted))
            ).all()
        )
    return set()


def delete_entity_related_rows(db: Session, typ: str, eid: int):
    if typ == "assignment":
        for l in db.scalars(select(Lesson).where(Lesson.assignment_id == eid)).all():
            db.delete(l)
        for fixed_lesson in db.scalars(
            select(FixedLesson).where(FixedLesson.assignment_id == eid)
        ).all():
            db.delete(fixed_lesson)
    if typ == "subject":
        for link in db.scalars(
            select(TeacherSubject).where(TeacherSubject.subject_id == eid)
        ).all():
            db.delete(link)
        for requirement in db.scalars(
            select(GradeSubjectRequirement).where(
                GradeSubjectRequirement.subject_id == eid
            )
        ).all():
            db.delete(requirement)
    if typ == "grade":
        for requirement in db.scalars(
            select(GradeSubjectRequirement).where(
                GradeSubjectRequirement.grade_id == eid
            )
        ).all():
            db.delete(requirement)
    if typ == "teacher":
        for link in db.scalars(
            select(TeacherSubject).where(TeacherSubject.teacher_id == eid)
        ).all():
            db.delete(link)
        for preference in db.scalars(
            select(TeacherPreference).where(TeacherPreference.teacher_id == eid)
        ).all():
            db.delete(preference)


def assignment_delete_impact(
    db: Session, assignment_ids: list[int]
) -> dict[str, list[int]]:
    """Return the exact schedule rows that would be removed with assignments.

    The IDs are used as the confirmation fingerprint, so a second delete request
    cannot silently remove schedule rows that appeared after the warning was shown.
    """
    wanted = {int(value) for value in assignment_ids if int(value) > 0}
    if not wanted:
        return {"lesson_ids": [], "fixed_lesson_ids": []}
    lesson_ids = sorted(
        db.scalars(select(Lesson.id).where(Lesson.assignment_id.in_(wanted))).all()
    )
    fixed_lesson_ids = sorted(
        db.scalars(
            select(FixedLesson.id).where(FixedLesson.assignment_id.in_(wanted))
        ).all()
    )
    return {"lesson_ids": lesson_ids, "fixed_lesson_ids": fixed_lesson_ids}


def assignment_delete_confirmation(
    impact: dict[str, list[int]],
    payload: EntityDeleteIn | None,
    *,
    assignment_count: int = 1,
):
    """Return a confirmation response unless the client confirmed this exact impact."""
    lesson_ids = impact["lesson_ids"]
    fixed_lesson_ids = impact["fixed_lesson_ids"]
    confirmed = bool(payload and payload.confirm_assignment_cascade)
    same_impact = bool(
        confirmed
        and sorted(set(payload.confirmed_lesson_ids)) == lesson_ids
        and sorted(set(payload.confirmed_fixed_lesson_ids)) == fixed_lesson_ids
    )
    if same_impact:
        return None

    noun = "phân công" if assignment_count == 1 else f"{assignment_count} phân công"
    if lesson_ids or fixed_lesson_ids:
        details = []
        if lesson_ids:
            details.append(f"{len(lesson_ids)} tiết đã xếp")
        if fixed_lesson_ids:
            details.append(f"{len(fixed_lesson_ids)} tiết ghim")
        message = (
            f"Xóa {noun} sẽ xóa luôn "
            + " và ".join(details)
            + " liên quan. Thao tác này không thể hoàn tác. Bạn có chắc muốn tiếp tục?"
        )
    else:
        message = f"Xóa {noun}? Thao tác này không thể hoàn tác."

    return JSONResponse(
        {
            "ok": False,
            "requires_confirmation": True,
            "message": message,
            "assignment_count": assignment_count,
            "affected_lessons": len(lesson_ids),
            "affected_fixed_lessons": len(fixed_lesson_ids),
            "lesson_ids": lesson_ids,
            "fixed_lesson_ids": fixed_lesson_ids,
        },
        409,
    )


__all__ = [name for name in globals() if not name.startswith("__")]
