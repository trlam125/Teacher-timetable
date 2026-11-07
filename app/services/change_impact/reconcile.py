from __future__ import annotations

from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import select

from app.models import Assignment, FixedLesson, Lesson
from app.scheduling.rules import assignment_requires_double, parse_slots, class_grade_blocked_slots
from app.services.schedule_operations.blocks import (
    fixed_coverage_slots, reconcile_assignment_lesson_blocks,
)
from app.services.schedule_operations.placement import lesson_slot_error


def groups_for(lessons):
    groups = defaultdict(list)
    for row in sorted(lessons, key=lambda row: (row.slot, row.id)):
        groups[row.block_id or f"legacy:{row.id}"].append(row)
    return list(groups.values())


def remove_groups(db, project, assignment, groups, reason):
    coverage = fixed_coverage_slots(db, project).get(assignment.id, set())
    for group in groups:
        if any(row.locked or row.slot in coverage for row in group):
            raise HTTPException(409, {
                "reason": "protected_lessons", "message": "Thay đổi xung đột với tiết ghim/cố định. Hãy bỏ cố định trước.",
                "lesson_ids": [row.id for row in group], "assignment_id": assignment.id,
                "slots": [row.slot for row in group],
            })
    reasons = db.info.setdefault("change_lesson_reasons", {})
    for group in groups:
        for row in group:
            reasons[row.id] = reason
            db.delete(row)
    db.flush()


def protect_assignment(db, project, assignment):
    rows = db.scalars(select(Lesson).where(Lesson.assignment_id == assignment.id)).all()
    if any(row.locked for row in rows) or db.scalar(select(FixedLesson.id).where(
        FixedLesson.assignment_id == assignment.id).limit(1)) is not None:
        raise HTTPException(409, {
            "reason": "protected_lessons", "message": "Phân công có tiết ghim/cố định. Hãy bỏ cố định trước khi xóa.",
            "assignment_id": assignment.id, "lesson_ids": [row.id for row in rows if row.locked],
        })


def remove_surplus_groups(db, project, assignment, rows):
    """Drop complete existing blocks, returning any overshoot to the tray."""
    excess = max(0, len(rows) - int(assignment.periods_per_week))
    if not excess:
        return rows
    coverage = fixed_coverage_slots(db, project).get(assignment.id, set())
    candidates = [group for group in reversed(groups_for(rows))
                  if not any(row.locked or row.slot in coverage for row in group)]
    chosen = []
    for group in candidates:
        if len(group) <= excess:
            chosen.append(group)
            excess -= len(group)
    if excess:
        # E.g. reducing four paired periods to three removes one whole pair.
        larger = next((group for group in candidates if group not in chosen and len(group) > excess), None)
        if larger is not None:
            chosen.append(larger)
            excess = 0
    if excess:
        raise HTTPException(409, "Số tiết mới không đủ để giữ các block ghim/cố định. Hãy bỏ cố định trước.")
    remove_groups(db, project, assignment, chosen, "Bỏ tiết dư do giảm số tiết/tuần")
    removed_ids = {row.id for group in chosen for row in group}
    return [row for row in rows if row.id not in removed_ids]


def reconcile_edit(db, project, assignment, *, old_mode, selected_ids=None, teacher_changed=False):
    """Keep valid blocks, remove only approved surplus/conflicts, never touch pins."""
    rows = db.scalars(select(Lesson).where(Lesson.assignment_id == assignment.id).order_by(Lesson.slot, Lesson.id)).all()
    # Validate the selection against the original timetable. A recalculation can
    # include blocks that the teacher change will already remove for conflicts.
    selected = set(selected_ids or [])
    if selected:
        groups = groups_for(rows)
        if not selected <= {row.id for row in rows}:
            raise HTTPException(400, "Danh sách tiết chọn bỏ không thuộc phân công hoặc không còn trên lịch.")
        chosen = [group for group in groups if selected.intersection(row.id for row in group)]
        if selected != {row.id for group in chosen for row in group}:
            raise HTTPException(400, "Hãy chọn toàn bộ block tiết đôi.")

    if teacher_changed:
        bad = [group for group in groups_for(rows) if any(
            lesson_slot_error(db, project, assignment, row.slot, exclude_lesson_id=row.id,
                              target_locked=bool(row.locked)) for row in group
        )]
        remove_groups(db, project, assignment, bad, "Xung đột lịch hoặc tiết tránh của giáo viên mới")
        rows = [row for row in rows if not any(row in group for group in bad)]

    if selected:
        # Conflicting blocks are already gone; retain their original reason and
        # remove only the other selected blocks still present on the timetable.
        chosen = [group for group in groups_for(rows) if selected.intersection(row.id for row in group)]
        remove_groups(db, project, assignment, chosen, "Bỏ tiết dư theo lựa chọn")
        rows = [row for row in rows if row.id not in selected]

    # Trim original blocks before converting pairs into independent singles.
    # The initial preview and subsequent checkbox selections must remove the same rows.
    if not assignment_requires_double(assignment):
        rows = remove_surplus_groups(db, project, assignment, rows)

    # Reuse the block reconciler for actual mode changes. Preserve protected metadata.
    if old_mode != assignment.block_mode or assignment_requires_double(assignment):
        protected = fixed_coverage_slots(db, project).get(assignment.id, set())
        pinned = {row.id: (row.slot, row.block_id, row.block_size, row.locked)
                  for group in groups_for(rows) if any(row.locked or row.slot in protected for row in group)
                  for row in group}
        before = {row.id for row in rows}
        rows, error = reconcile_assignment_lesson_blocks(db, project, assignment, rows, old_mode=old_mode)
        if error:
            raise HTTPException(409, error)
        current = {row.id: (row.slot, row.block_id, row.block_size, row.locked) for row in rows}
        changed_pins = [lid for lid, state in pinned.items() if current.get(lid) != state]
        if changed_pins:
            raise HTTPException(409, {
                "reason": "protected_lessons", "lesson_ids": changed_pins,
                "message": "Hãy bỏ cố định các block liên quan trước khi đổi cấu trúc tiết đơn/đôi.",
            })
        reasons = db.info.setdefault("change_lesson_reasons", {})
        for row_id in before - {row.id for row in rows}:
            reasons[row_id] = "Điều chỉnh cấu trúc block hoặc số tiết theo chương trình mới"

    rows = remove_surplus_groups(db, project, assignment, rows)
    return db.scalars(select(Lesson).where(Lesson.assignment_id == assignment.id).order_by(Lesson.slot, Lesson.id)).all()


def remove_class_conflicts(db, project, school_class):
    blocked = class_grade_blocked_slots(school_class) | set(parse_slots(school_class.unavailable_json))
    for assignment in db.scalars(select(Assignment).where(Assignment.class_id == school_class.id)).all():
        rows = db.scalars(select(Lesson).where(Lesson.assignment_id == assignment.id)).all()
        groups = [group for group in groups_for(rows) if any(row.slot in blocked for row in group)]
        remove_groups(db, project, assignment, groups, "Xung đột khóa lịch của khối mới")
