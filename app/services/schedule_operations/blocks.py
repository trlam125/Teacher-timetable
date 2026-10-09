from __future__ import annotations

import secrets
from app.models import Assignment, FixedLesson, Lesson, Project
from app.scheduling.rules import (
    assignment_groups,
    assignment_requires_double,
    fixed_row_size,
    required_double_block_state,
    slot_meta,
)
from collections import Counter, defaultdict
from sqlalchemy import select
from sqlalchemy.orm import Session


def new_schedule_block_id() -> str:
    """Return a compact opaque identity shared by every Lesson in one block."""
    return secrets.token_hex(16)


def lesson_block_members(lessons: list[Lesson], lesson: Lesson) -> list[Lesson]:
    """Return the persisted atomic block containing ``lesson``.

    block_id is authoritative. A missing id is treated as a one-lesson legacy
    block only as a defensive fallback; migrate_schema() backfills old rows.
    """
    block_id = getattr(lesson, "block_id", None)
    if not block_id:
        return [lesson]
    return sorted(
        [row for row in lessons if getattr(row, "block_id", None) == block_id],
        key=lambda row: row.slot,
    )


def reconcile_assignment_lesson_blocks(
    db: Session,
    project: Project,
    assignment: Assignment,
    lessons: list[Lesson],
    *,
    old_mode: str,
) -> tuple[list[Lesson], str | None]:
    """Reconcile scheduled Lesson blocks after periods/mode changes.

    Compatible blocks are preserved. Incompatible *unlocked* rows are returned
    to the tray (deleted from the timetable); locked blocks are never silently
    changed. When possible, adjacent unlocked singles are paired and an excess
    unlocked pair may be reduced to one single to preserve a placed period.
    """
    rows = list(lessons)
    if not assignment_requires_double(assignment):
        # Free/preferred periods are independent scheduling units.
        for row in rows:
            row.block_id = new_schedule_block_id()
            row.block_size = 1
        return rows, None

    # Group by persisted identity. Defensive legacy fallback treats a missing
    # id as an independent single instead of guessing from adjacency.
    groups = []
    by_id = defaultdict(list)
    for row in rows:
        by_id[row.block_id or f"legacy-single:{row.id}"].append(row)
    for block_id, members in by_id.items():
        members.sort(key=lambda item: item.slot)
        declared = {int(getattr(item, "block_size", 1) or 1) for item in members}
        if len(declared) != 1:
            return rows, "Có block cũ có metadata kích thước không thống nhất."
        declared_size = declared.pop()
        if old_mode == "required_double" and declared_size != len(members):
            return (
                rows,
                "Có block bắt buộc tiết đôi bị thiếu tiết; hãy tạo lại lịch trước khi đổi chế độ.",
            )
        if len(members) > 2:
            return (
                rows,
                "Có block cũ lớn hơn 2 tiết; hãy tạo lại lịch trước khi đổi chế độ.",
            )
        if len(members) == 2:
            left, right = members
            if (
                slot_meta(project, left.slot)[:2] != slot_meta(project, right.slot)[:2]
                or right.slot != left.slot + 1
            ):
                return rows, "Có block đôi cũ không liên tiếp trong cùng buổi."
        locked_count = sum(1 for row in members if row.locked)
        if locked_count not in {0, len(members)}:
            return (
                rows,
                "Có block chỉ cố định một phần; hãy bỏ cố định trước khi đổi cấu trúc.",
            )
        groups.append(
            {
                "id": block_id,
                "members": members,
                "size": len(members),
                "locked": bool(locked_count),
            }
        )

    # Stable left-to-right reconciliation keeps mode/period edits deterministic
    # even when PostgreSQL returns Lesson rows in a different physical order.
    groups.sort(key=lambda group: group["members"][0].slot)

    desired = Counter(assignment_groups(assignment))
    kept = []
    spare_singles = []
    spare_pairs = []

    # Locked blocks must fit the new structure exactly.
    used = Counter()
    for group in groups:
        if not group["locked"]:
            continue
        size = group["size"]
        if used[size] >= desired[size]:
            return (
                rows,
                "Thay đổi mới không còn chỗ cho một block đang cố định. Hãy bỏ cố định block đó trước.",
            )
        used[size] += 1
        kept.append(group)

    # Preserve already-correct unlocked double blocks first. Singles are held
    # back temporarily because two adjacent singles may preserve more scheduled
    # periods by becoming a required pair.
    for group in groups:
        if group["locked"]:
            continue
        size = group["size"]
        if size == 2:
            if used[2] < desired[2]:
                used[2] += 1
                kept.append(group)
            else:
                spare_pairs.append(group)
        else:
            spare_singles.append(group)

    # Pair adjacent spare singles before consuming the one optional odd single.
    while used[2] < desired[2]:
        match = None
        for i, left_group in enumerate(spare_singles):
            left = left_group["members"][0]
            for j, right_group in enumerate(spare_singles[i + 1 :], i + 1):
                right = right_group["members"][0]
                a, b = sorted((left, right), key=lambda row: row.slot)
                if (
                    slot_meta(project, a.slot)[:2] == slot_meta(project, b.slot)[:2]
                    and b.slot == a.slot + 1
                ):
                    match = (i, j, a, b)
                    break
            if match:
                break
        if not match:
            break
        i, j, a, b = match
        block_id = new_schedule_block_id()
        a.block_id = block_id
        b.block_id = block_id
        a.block_size = 2
        b.block_size = 2
        kept.append({"id": block_id, "members": [a, b], "size": 2, "locked": False})
        for index in sorted((i, j), reverse=True):
            spare_singles.pop(index)
        used[2] += 1

    # Keep the optional odd single only after all preservable pairs were formed.
    while used[1] < desired[1] and spare_singles:
        group = spare_singles.pop(0)
        member = group["members"][0]
        if not member.block_id:
            member.block_id = new_schedule_block_id()
        member.block_size = 1
        kept.append(
            {"id": member.block_id, "members": [member], "size": 1, "locked": False}
        )
        used[1] += 1

    # If a single is still required but all remaining material is a pair,
    # preserve the first period and return only the second period to the tray.
    while used[1] < desired[1] and spare_pairs:
        group = spare_pairs.pop(0)
        keep = group["members"][0]
        drop = group["members"][1]
        db.delete(drop)
        keep.block_id = new_schedule_block_id()
        keep.block_size = 1
        kept.append(
            {"id": keep.block_id, "members": [keep], "size": 1, "locked": False}
        )
        used[1] += 1

    # Any blocks that cannot belong to the new structure are returned to tray.
    kept_ids = {id(row) for group in kept for row in group["members"]}
    kept_size_by_row = {
        id(row): group["size"] for group in kept for row in group["members"]
    }
    remaining = []
    for row in rows:
        if id(row) in kept_ids:
            if not row.block_id:
                row.block_id = new_schedule_block_id()
            row.block_size = kept_size_by_row[id(row)]
            remaining.append(row)
        else:
            db.delete(row)
    db.flush()
    return remaining, None


def normalize_assignment_fixed_rows(
    db: Session,
    project: Project,
    assignment: Assignment,
    lessons: list[Lesson],
) -> str | None:
    """Rebuild FixedLesson metadata from persisted block identities."""
    replacement_rows = []
    if assignment_requires_double(assignment):
        state = required_double_block_state(project, assignment, lessons)
        if not state["valid"]:
            return state["reason"] or "Cấu trúc block bắt buộc tiết đôi không hợp lệ."
        for group in state["groups"]:
            members = group["lessons"]
            locked_count = sum(1 for lesson in members if lesson.locked)
            if locked_count not in {0, len(members)}:
                return (
                    "Một block chỉ được cố định toàn bộ. Hãy bỏ cố định block bị thiếu "
                    "hoặc xếp lại trước khi tiếp tục."
                )
            if locked_count:
                replacement_rows.append((group["start"], group["size"]))
    else:
        replacement_rows = [(lesson.slot, 1) for lesson in lessons if lesson.locked]

    fixed_rows = db.scalars(
        select(FixedLesson).where(
            FixedLesson.project_id == project.id,
            FixedLesson.assignment_id == assignment.id,
        )
    ).all()
    for row in fixed_rows:
        db.delete(row)
    db.flush()
    for slot, size in replacement_rows:
        db.add(
            FixedLesson(
                project_id=project.id,
                assignment_id=assignment.id,
                slot=slot,
                group_size=size,
            )
        )
    return None


def fixed_coverage_slots(db: Session, project: Project):
    """Trả về các ô phải khóa theo mọi FixedLesson của project."""
    assignments = {
        assignment.id: assignment
        for assignment in db.scalars(
            select(Assignment).where(Assignment.project_id == project.id)
        ).all()
    }
    lessons_by_assignment = defaultdict(list)
    for lesson in db.scalars(
        select(Lesson).where(Lesson.project_id == project.id)
    ).all():
        lessons_by_assignment[lesson.assignment_id].append(lesson)

    coverage = defaultdict(set)
    for row in db.scalars(
        select(FixedLesson).where(FixedLesson.project_id == project.id)
    ).all():
        assignment = assignments.get(row.assignment_id)
        if not assignment:
            continue
        size = fixed_row_size(
            project,
            assignment,
            row,
            lessons_by_assignment[assignment.id],
        )
        if size < 1:
            # Bảo vệ tối thiểu ô neo để các thao tác kéo/xóa không làm mất
            # dữ liệu ghim legacy. Đây chỉ là coverage phòng thủ, KHÔNG phải
            # xác nhận metadata hợp lệ: schedule_input_validation_report() sẽ
            # luôn báo FixedLesson này là lỗi cho Generate/Share/Export.
            coverage[assignment.id].add(row.slot)
            continue
        coverage[assignment.id].update(range(row.slot, row.slot + size))
    return coverage


def add_generated_lessons(
    db: Session,
    project: Project,
    rows,
):
    """Persist solver rows while preserving each solver task as one block.

    Rows may be the legacy ``(assignment_id, slot, locked)`` form or the new
    ``(..., block_token)`` form. A token is translated to one opaque persistent
    block_id for every lesson emitted by that solver task.
    """
    fixed_slots = fixed_coverage_slots(db, project)
    rows = list(rows)
    token_sizes = Counter(
        (row[0], str(row[3])) for row in rows if len(row) >= 4 and row[3] is not None
    )
    block_ids = {}
    for row in rows:
        assignment_id, slot, locked = row[:3]
        token = row[3] if len(row) >= 4 else None
        if token is None:
            block_id = new_schedule_block_id()
            block_size = 1
        else:
            key = (assignment_id, str(token))
            block_id = block_ids.setdefault(key, new_schedule_block_id())
            block_size = int(token_sizes[key])
        db.add(
            Lesson(
                project_id=project.id,
                assignment_id=assignment_id,
                slot=slot,
                block_id=block_id,
                block_size=block_size,
                locked=bool(locked or slot in fixed_slots[assignment_id]),
            )
        )
