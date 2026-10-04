from __future__ import annotations

from fastapi import APIRouter
from app.services.runtime import *

router = APIRouter()


@router.post("/api/projects/{pid}/fixed")
def fixed(
    pid: int,
    payload: FixedIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    p = get_project_for_update(pid, user, db)
    assignment = db.get(Assignment, payload.assignment_id)
    if not assignment or assignment.project_id != pid:
        raise HTTPException(404)
    lessons = db.scalars(
        select(Lesson).where(
            Lesson.project_id == pid, Lesson.assignment_id == assignment.id
        )
    ).all()
    slots = {lesson.slot for lesson in lessons}
    if payload.slot not in slots:
        raise HTTPException(400, "Hãy chọn một tiết đang có trên lịch để cố định")
    selected_lesson = next((row for row in lessons if row.slot == payload.slot), None)
    members = (
        lesson_block_members(lessons, selected_lesson)
        if assignment_requires_double(assignment) and selected_lesson
        else [selected_lesson]
    )
    run_slots = {row.slot for row in members if row is not None}
    for lesson in lessons:
        if lesson.slot in run_slots:
            error = lesson_slot_error(
                db, p, assignment, lesson.slot, lesson.id, target_locked=True
            )
            if error:
                raise HTTPException(409, error)
    # One user action pins exactly the persisted scheduling block. Required
    # double periods therefore lock atomically; neighboring blocks are untouched.
    coverage = fixed_coverage_slots(db, p).get(assignment.id, set())
    if not coverage.issubset(slots):
        raise HTTPException(
            409,
            "Có cụm cố định đang thiếu tiết. Hãy xếp bổ sung hoặc bỏ ghim đó trước khi cố định thêm.",
        )
    for lesson in lessons:
        if lesson.slot in run_slots or lesson.slot in coverage:
            lesson.locked = True
    error = normalize_assignment_fixed_rows(db, p, assignment, lessons)
    if error:
        db.rollback()
        raise HTTPException(409, error)
    db.flush()
    if not assignment_completion_feasible(db, p, assignment, slots):
        db.rollback()
        raise HTTPException(
            409,
            "Lịch hiện tại không thể hoàn thành hợp lệ. Hãy điều chỉnh trước khi ghim.",
        )
    db.commit()
    return {
        "ok": True,
        "pinned": len(run_slots),
        "message": f"Đã cố định cả cụm {len(run_slots)} tiết."
        if len(run_slots) > 1
        else "Đã cố định tiết đang chọn.",
    }


@router.delete("/api/projects/{pid}/fixed/{assignment_id}/{slot}")
def remove_fixed_group(
    pid: int,
    assignment_id: int,
    slot: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    p = get_project_for_update(pid, user, db)
    assignment = db.get(Assignment, assignment_id)
    if not assignment or assignment.project_id != pid:
        raise HTTPException(404)
    lessons = db.scalars(
        select(Lesson).where(
            Lesson.project_id == pid, Lesson.assignment_id == assignment_id
        )
    ).all()
    rows = db.scalars(
        select(FixedLesson).where(
            FixedLesson.project_id == pid, FixedLesson.assignment_id == assignment_id
        )
    ).all()
    selected_lesson = next((row for row in lessons if row.slot == slot), None)
    members = (
        lesson_block_members(lessons, selected_lesson)
        if assignment_requires_double(assignment) and selected_lesson
        else [selected_lesson]
    )
    run_slots = {row.slot for row in members if row is not None} or {slot}
    targets = []
    for row in rows:
        size = max(1, fixed_row_size(p, assignment, row, lessons))
        if run_slots.intersection(range(row.slot, row.slot + size)):
            targets.append((row, size))
    if not targets and not any(
        item.locked and item.slot in run_slots for item in lessons
    ):
        raise HTTPException(404, "Không tìm thấy cụm tiết cố định")
    unlocked = set(run_slots)
    for row, size in targets:
        unlocked.update(range(row.slot, row.slot + size))
        db.delete(row)
    remaining = []
    for row in rows:
        if all(row.id != target.id for target, _size in targets):
            size = fixed_row_size(p, assignment, row, lessons)
            if size < 1:
                continue
            remaining.extend(range(row.slot, row.slot + size))
    for lesson in lessons:
        if lesson.slot in unlocked and lesson.slot not in remaining:
            lesson.locked = False
    db.commit()
    released_count = len(unlocked - set(remaining))
    return {
        "ok": True,
        "message": (
            f"Đã bỏ cố định cả block {released_count} tiết."
            if released_count > 1
            else "Đã bỏ cố định tiết đang chọn."
        ),
    }


@router.delete("/api/projects/{pid}/fixed/{assignment_id}")
def remove_fixed(
    pid: int,
    assignment_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    get_project_for_update(pid, user, db)
    assignment = db.get(Assignment, assignment_id)
    if not assignment or assignment.project_id != pid:
        raise HTTPException(404)
    fixed_rows = db.scalars(
        select(FixedLesson).where(
            FixedLesson.project_id == pid, FixedLesson.assignment_id == assignment_id
        )
    ).all()
    for row in fixed_rows:
        db.delete(row)
    lessons = db.scalars(
        select(Lesson).where(
            Lesson.project_id == pid, Lesson.assignment_id == assignment_id
        )
    ).all()
    for lesson in lessons:
        lesson.locked = False
    db.commit()
    return {"ok": True, "message": "Đã bỏ toàn bộ cố định của phân công."}
