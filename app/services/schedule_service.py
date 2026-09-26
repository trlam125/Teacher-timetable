from __future__ import annotations

from app.services.foundation import *
from app.services.schedule_validation import *

def assignment_feasibility_context(
    db: Session,
    project: Project,
    assignment: Assignment,
):
    """Preload immutable inputs reused while evaluating many candidate slots."""
    pps = project.periods_per_session
    ppd = project.sessions * pps
    teacher = db.get(Teacher, assignment.teacher_id)
    school_class = db.get(SchoolClass, assignment.class_id)
    subject = db.get(Subject, assignment.subject_id)
    if not teacher or not school_class or not subject:
        return None

    assignments = {row.id: row for row in db.scalars(
        select(Assignment).where(Assignment.project_id == project.id)
    ).all()}
    lessons = db.scalars(
        select(Lesson).where(Lesson.project_id == project.id)
    ).all()
    forbidden = (
        parse_slots(project.blocked_slots_json)
        | parse_slots(teacher.unavailable_json)
        | parse_slots(school_class.unavailable_json)
    )
    teacher_day = Counter()
    subject_masks = defaultdict(int)
    for lesson in lessons:
        if lesson.assignment_id == assignment.id:
            continue
        other = assignments.get(lesson.assignment_id)
        if not other:
            continue
        if other.teacher_id == assignment.teacher_id:
            forbidden.add(lesson.slot)
            teacher_day[lesson.slot // ppd] += 1
        if other.class_id == assignment.class_id:
            forbidden.add(lesson.slot)
            if other.subject_id == assignment.subject_id:
                subject_masks[lesson.slot // pps] |= 1 << (lesson.slot % pps)

    fixed_rows = db.scalars(select(FixedLesson).where(
        FixedLesson.project_id == project.id,
        FixedLesson.assignment_id == assignment.id,
    )).all()
    same_lessons = [row for row in lessons if row.assignment_id == assignment.id]
    specs = [
        (row.slot, fixed_row_size(project, assignment, row, same_lessons))
        for row in fixed_rows
    ]
    fixed_error = fixed_group_validation_error(
        assignment_groups(assignment),
        specs,
        days=project.days,
        sessions=project.sessions,
        periods_per_session=pps,
    )
    return {
        "teacher": teacher,
        "subject": subject,
        "forbidden": forbidden,
        "teacher_day": teacher_day,
        "subject_masks": subject_masks,
        "specs": specs,
        "same_lessons": same_lessons,
        "fixed_error": fixed_error,
    }


def assignment_completion_feasible(
    db: Session,
    project: Project,
    assignment: Assignment,
    proposed_slots: list[int] | set[int],
    *,
    enforce_pattern: bool = True,
    context=None,
) -> bool:
    """Exact bounded DP over session masks (at most 2**8 per session).

    Avoid exploring permutations of every remaining period. A state only needs
    the number of periods and compulsory singles used; day budgets are applied
    before combining days. Existing and fixed slots must be covered exactly.
    """
    values = list(proposed_slots)
    current = set(values)
    total = int(assignment.periods_per_week)
    pps = project.periods_per_session
    ppd = project.sessions * pps
    maximum = project.days * ppd
    if len(values) != len(current) or len(current) > total:
        return False
    if any(slot < 0 or slot >= maximum for slot in current):
        return False
    feasibility = context or assignment_feasibility_context(db, project, assignment)
    if not feasibility or feasibility["fixed_error"]:
        return False
    teacher = feasibility["teacher"]
    subject = feasibility["subject"]
    forbidden = feasibility["forbidden"]
    teacher_day = feasibility["teacher_day"]
    subject_masks = feasibility["subject_masks"]
    specs = feasibility["specs"]
    same_lessons = feasibility["same_lessons"]
    required = set(current)
    forced_by_session = defaultdict(dict)
    for start, size in specs:
        required.update(range(start, start + size))
        forced_by_session[start // pps][start % pps] = size
    # A locked row without metadata must also stay covered (legacy projects).
    required.update(row.slot for row in same_lessons if row.locked)
    if len(required) > total or required.intersection(forbidden):
        return False
    double = assignment_requires_double(assignment) and enforce_pattern
    single_limit = total % 2 if double else 0
    max_run = max(1, int(subject.max_consecutive or 1))
    reachable = {(0, 0)}
    for day in range(project.days):
        budget = min(total, teacher.max_periods_day - teacher_day[day])
        if budget < 0:
            return False
        day_options = {(0, 0)}
        for session in range(project.sessions):
            key = day * project.sessions + session
            base = key * pps
            allowed = sum(1 << i for i in range(pps) if base + i not in forbidden)
            mandatory = sum(1 << i for i in range(pps) if base + i in required)
            forced = forced_by_session[key]
            options = set()
            mask = allowed
            while True:
                count = mask.bit_count()
                if mask & mandatory == mandatory and count <= budget:
                    occupied = mask | subject_masks[key]
                    run = longest = 0
                    for i in range(pps):
                        run = run + 1 if occupied & (1 << i) else 0
                        longest = max(longest, run)
                    if longest <= max_run:
                        singles = 0
                        if double:
                            # Fixed groups split a run into independent segments;
                            # never let a new pair consume half an explicit pin.
                            cursor = 0
                            while cursor < pps:
                                if not mask & (1 << cursor):
                                    cursor += 1
                                elif cursor in forced:
                                    size = forced[cursor]
                                    singles += size % 2
                                    cursor += size
                                else:
                                    start = cursor
                                    while cursor < pps and mask & (1 << cursor) and cursor not in forced:
                                        cursor += 1
                                    singles += (cursor - start) % 2
                        if singles <= single_limit:
                            options.add((count, singles))
                if mask == 0:
                    break
                mask = (mask - 1) & allowed
            day_options = {(used + added, odd + extra)
                           for used, odd in day_options for added, extra in options
                           if used + added <= budget and odd + extra <= single_limit}
            if not day_options:
                return False
        reachable = {(used + added, odd + extra)
                     for used, odd in reachable for added, extra in day_options
                     if used + added <= total and odd + extra <= single_limit}
        if not reachable:
            return False
    return (total, single_limit) in reachable


def assignment_pattern_label(assignment: Assignment):
    if assignment_requires_double(assignment):
        return (
            "bắt buộc tiết đôi ("
            + " + ".join(str(value) for value in assignment_groups(assignment))
            + ")"
        )
    if assignment_prefers_double(assignment):
        return "ưu tiên tiết đôi"
    return "xếp tiết tự do"

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
            return rows, "Có block bắt buộc tiết đôi bị thiếu tiết; hãy tạo lại lịch trước khi đổi chế độ."
        if len(members) > 2:
            return rows, "Có block cũ lớn hơn 2 tiết; hãy tạo lại lịch trước khi đổi chế độ."
        if len(members) == 2:
            left, right = members
            if slot_meta(project, left.slot)[:2] != slot_meta(project, right.slot)[:2] or right.slot != left.slot + 1:
                return rows, "Có block đôi cũ không liên tiếp trong cùng buổi."
        locked_count = sum(1 for row in members if row.locked)
        if locked_count not in {0, len(members)}:
            return rows, "Có block chỉ cố định một phần; hãy bỏ cố định trước khi đổi cấu trúc."
        groups.append({"id": block_id, "members": members, "size": len(members), "locked": bool(locked_count)})

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
            return rows, "Thay đổi mới không còn chỗ cho một block đang cố định. Hãy bỏ cố định block đó trước."
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
        kept.append({"id": member.block_id, "members": [member], "size": 1, "locked": False})
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
        kept.append({"id": keep.block_id, "members": [keep], "size": 1, "locked": False})
        used[1] += 1

    # Any blocks that cannot belong to the new structure are returned to tray.
    kept_ids = {id(row) for group in kept for row in group["members"]}
    kept_size_by_row = {id(row): group["size"] for group in kept for row in group["members"]}
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
        replacement_rows = [
            (lesson.slot, 1) for lesson in lessons if lesson.locked
        ]

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

def _minimal_schedule_invalid_lesson_analysis(
    db: Session,
    project: Project,
    assignments: list[Assignment],
    lessons: list[Lesson],
) -> list[tuple[Lesson, str]]:
    """Return only the lessons that must be rejected, with UI-safe reasons.

    Lessons are evaluated in the same deterministic order used by integrity
    validation: locked lessons first, then movable lessons by slot/id. A lesson
    is marked invalid only when adding that lesson would introduce a hard
    conflict. This keeps aggregate limits (daily teacher load and consecutive
    subject periods) minimal instead of incorrectly marking the whole group.
    """
    assignment_by_id = {assignment.id: assignment for assignment in assignments}
    teachers = {
        teacher.id: teacher
        for teacher in db.scalars(
            select(Teacher).where(Teacher.project_id == project.id)
        ).all()
    }
    classes = {
        school_class.id: school_class
        for school_class in db.scalars(
            select(SchoolClass).where(SchoolClass.project_id == project.id)
        ).all()
    }
    subjects = {
        subject.id: subject
        for subject in db.scalars(
            select(Subject).where(Subject.project_id == project.id)
        ).all()
    }
    teacher_unavailable = {
        teacher_id: parse_slots(teacher.unavailable_json)
        for teacher_id, teacher in teachers.items()
    }
    class_unavailable = {
        class_id: parse_slots(school_class.unavailable_json)
        for class_id, school_class in classes.items()
    }

    maximum = project.days * project.sessions * project.periods_per_session
    periods_per_day = project.sessions * project.periods_per_session
    blocked = parse_slots(project.blocked_slots_json)

    teacher_slot_busy: set[tuple[int, int]] = set()
    class_slot_busy: set[tuple[int, int]] = set()
    teacher_day_counts: Counter[tuple[int, int]] = Counter()
    class_subject_session_periods: dict[tuple[int, int, int, int], set[int]] = (
        defaultdict(set)
    )
    invalid: list[tuple[Lesson, str]] = []

    def reject(lesson: Lesson, reason: str) -> None:
        invalid.append((lesson, reason))

    def exceeds_subject_run(periods: set[int], candidate: int, limit: int) -> bool:
        ordered = sorted(periods | {candidate})
        longest = current = 0
        previous = None
        for period in ordered:
            current = (
                current + 1 if previous is not None and period == previous + 1 else 1
            )
            longest = max(longest, current)
            previous = period
        return longest > limit

    ordered_lessons = sorted(
        lessons,
        key=lambda lesson: (
            0 if bool(lesson.locked) else 1,
            int(lesson.slot),
            int(lesson.id or 0),
        ),
    )

    for lesson in ordered_lessons:
        assignment = assignment_by_id.get(lesson.assignment_id)
        if not assignment:
            reject(lesson, "Tiết học tham chiếu phân công không còn tồn tại.")
            continue

        teacher = teachers.get(assignment.teacher_id)
        school_class = classes.get(assignment.class_id)
        subject = subjects.get(assignment.subject_id)
        if not teacher or not school_class or not subject:
            reject(lesson, "Phân công không còn đầy đủ lớp, môn hoặc giáo viên.")
            continue

        slot = int(lesson.slot)
        if slot < 0 or slot >= maximum:
            reject(lesson, "Ô thời khóa biểu không hợp lệ.")
            continue
        if slot in blocked:
            reject(lesson, "Tiết này đã bị khóa toàn trường.")
            continue
        if slot in teacher_unavailable[teacher.id]:
            reject(lesson, f"Giáo viên {teacher.name} không thể dạy ở tiết này.")
            continue
        if slot in class_unavailable[school_class.id]:
            reject(lesson, f"Lớp {school_class.name} không học ở tiết này.")
            continue

        day = slot // periods_per_day
        inside_day = slot % periods_per_day
        session = inside_day // project.periods_per_session
        period = inside_day % project.periods_per_session
        teacher_slot_key = (assignment.teacher_id, slot)
        class_slot_key = (assignment.class_id, slot)
        teacher_day_key = (assignment.teacher_id, day)
        subject_run_key = (assignment.class_id, assignment.subject_id, day, session)

        if teacher_slot_key in teacher_slot_busy:
            reject(lesson, f"Trùng lịch giáo viên {teacher.name} trong cùng một tiết.")
            continue
        if class_slot_key in class_slot_busy:
            reject(lesson, f"Trùng lịch lớp {school_class.name} trong cùng một tiết.")
            continue

        daily_limit = int(teacher.max_periods_day or 0)
        if teacher_day_counts[teacher_day_key] >= daily_limit:
            reject(
                lesson,
                f"Giáo viên {teacher.name} vượt giới hạn {daily_limit} tiết/ngày.",
            )
            continue

        consecutive_limit = int(subject.max_consecutive or 0)
        if exceeds_subject_run(
            class_subject_session_periods[subject_run_key],
            period,
            consecutive_limit,
        ):
            reject(
                lesson,
                f"Môn {subject.name} vượt giới hạn {consecutive_limit} tiết liên tiếp.",
            )
            continue

        teacher_slot_busy.add(teacher_slot_key)
        class_slot_busy.add(class_slot_key)
        teacher_day_counts[teacher_day_key] += 1
        class_subject_session_periods[subject_run_key].add(period)

    return invalid


def minimal_schedule_invalid_lessons(
    db: Session,
    project: Project,
    assignments: list[Assignment],
    lessons: list[Lesson],
) -> list[Lesson]:
    """Keep the maximum valid subset and return only truly invalid lessons."""
    return [
        lesson
        for lesson, _reason in _minimal_schedule_invalid_lesson_analysis(
            db, project, assignments, lessons
        )
    ]

def schedule_ui_validation_report(
    db: Session,
    project: Project,
) -> dict:
    """Return lightweight server-authoritative validation used by the editor UI.

    Required-double decisions stay on the backend and are validated from the
    persisted ``block_id``/``block_size`` structure. The browser never infers
    required pairs from neighboring timetable cells.
    """
    assignments = db.scalars(
        select(Assignment).where(Assignment.project_id == project.id)
    ).all()
    lessons = db.scalars(
        select(Lesson).where(Lesson.project_id == project.id)
    ).all()
    fixed_rows = db.scalars(
        select(FixedLesson).where(FixedLesson.project_id == project.id)
    ).all()
    invalid_analysis = _minimal_schedule_invalid_lesson_analysis(
        db, project, assignments, lessons
    )

    lessons_by_assignment: dict[int, list[Lesson]] = defaultdict(list)
    for lesson in lessons:
        lessons_by_assignment[lesson.assignment_id].append(lesson)

    fixed_by_assignment: dict[int, list[FixedLesson]] = defaultdict(list)
    for row in fixed_rows:
        fixed_by_assignment[row.assignment_id].append(row)

    required_double_conflicts = []
    for assignment in assignments:
        if not assignment_requires_double(assignment):
            continue
        rows = lessons_by_assignment.get(assignment.id, [])
        if not rows:
            continue

        slots = [int(row.slot) for row in rows]
        block_state = required_double_block_state(project, assignment, rows)
        if block_state["valid"]:
            continue

        expected = int(assignment.periods_per_week or 0)
        actual = len(slots)
        if actual > expected:
            message = (
                f"Phân công bắt buộc tiết đôi đang có {actual}/{expected} tiết, "
                "vượt số tiết/tuần đã cấu hình."
            )
        else:
            message = (
                "Cấu trúc block bắt buộc tiết đôi hiện không hợp lệ. "
                + (block_state.get("reason") or "Hãy tạo lại hoặc xếp lại block.")
            )
        required_double_conflicts.append(
            {
                "assignment_id": assignment.id,
                "lesson_ids": [row.id for row in rows],
                "message": message,
            }
        )

    return {
        "invalid_lesson_ids": [lesson.id for lesson, _reason in invalid_analysis],
        "invalid_lesson_conflicts": [
            {"lesson_id": lesson.id, "message": reason}
            for lesson, reason in invalid_analysis
        ],
        "required_double_conflicts": required_double_conflicts,
    }

def schedule_integrity_report(
    db: Session,
    project: Project,
) -> dict:
    """Return the authoritative timetable integrity diagnostic report.

    Generation/final solver validation may still use this as a hard gate. Sharing
    and Excel export intentionally do not: users can publish/export the timetable
    in its current state and use this report separately to see remaining issues.
    """
    assignments = db.scalars(
        select(Assignment).where(Assignment.project_id == project.id)
    ).all()
    classes = db.scalars(
        select(SchoolClass).where(SchoolClass.project_id == project.id)
    ).all()
    input_report = schedule_input_validation_report(
        db, project, assignments=assignments, classes=classes
    )
    lessons = db.scalars(
        select(Lesson).where(Lesson.project_id == project.id)
    ).all()

    invalid_lessons = minimal_schedule_invalid_lessons(
        db, project, assignments, lessons
    )
    by_assignment: dict[int, list[Lesson]] = defaultdict(list)
    for lesson in lessons:
        by_assignment[lesson.assignment_id].append(lesson)

    count_errors = []
    required_double_errors = []
    for assignment in assignments:
        rows = by_assignment.get(assignment.id, [])
        expected = int(assignment.periods_per_week or 0)
        actual = len(rows)
        if actual != expected:
            count_errors.append(
                {
                    "assignment_id": assignment.id,
                    "expected": expected,
                    "actual": actual,
                }
            )
            continue
        if assignment_requires_double(assignment):
            block_state = required_double_block_state(project, assignment, rows)
            if not block_state["valid"] or block_state["missing_sizes"]:
                required_double_errors.append(assignment.id)

    fixed_coverage = fixed_coverage_slots(db, project)
    fixed_errors = []
    for assignment_id, expected_slots in fixed_coverage.items():
        rows = by_assignment.get(assignment_id, [])
        actual_locked = {lesson.slot for lesson in rows if lesson.locked}
        missing_slots = sorted(expected_slots - actual_locked)
        if missing_slots:
            fixed_errors.append(
                {
                    "assignment_id": assignment_id,
                    "missing_slots": missing_slots,
                }
            )

    schedule_issue_count = (
        len(invalid_lessons)
        + len(count_errors)
        + len(required_double_errors)
        + len(fixed_errors)
    )
    issue_count = input_report["issue_count"] + schedule_issue_count
    valid = issue_count == 0

    if valid:
        message = "Thời khóa biểu hợp lệ. Bạn có thể chia sẻ hoặc xuất Excel."
    else:
        parts = []
        if input_report["assignment_reference_issues"]:
            parts.append(
                f"{len(input_report['assignment_reference_issues'])} phân công tham chiếu dữ liệu sai"
            )
        if input_report["duplicate_assignment_issues"]:
            parts.append(
                f"{len(input_report['duplicate_assignment_issues'])} lớp–môn bị phân công trùng"
            )
        if input_report["grade_requirement_issues"]:
            parts.append(
                f"{len(input_report['grade_requirement_issues'])} phân công lệch chương trình khối"
            )
        if input_report["teacher_subject_issues"]:
            parts.append(
                f"{len(input_report['teacher_subject_issues'])} phân công sai chuyên môn giáo viên"
            )
        if input_report["capacity_issues"]:
            parts.append(
                f"{len(input_report['capacity_issues'])} giáo viên vượt tải khả dụng"
            )
        if input_report["class_capacity_issues"]:
            parts.append(
                f"{len(input_report['class_capacity_issues'])} lớp vượt số ô khả dụng"
            )
        if input_report["fixed_definition_issues"]:
            parts.append(
                f"{len(input_report['fixed_definition_issues'])} dữ liệu tiết cố định không hợp lệ"
            )
        if input_report["assignment_availability_issues"]:
            parts.append(
                f"{len(input_report['assignment_availability_issues'])} phân công không đủ ô cùng khả dụng"
            )
        if invalid_lessons:
            parts.append(f"{len(invalid_lessons)} tiết vi phạm ràng buộc")
        if count_errors:
            parts.append(f"{len(count_errors)} phân công chưa đúng số tiết")
        if required_double_errors:
            parts.append(
                f"{len(required_double_errors)} phân công sai mẫu bắt buộc tiết đôi"
            )
        if fixed_errors:
            parts.append(f"{len(fixed_errors)} cụm cố định không còn toàn vẹn")
        message = (
            "Thời khóa biểu còn lỗi: "
            + ", ".join(parts)
            + ". Bạn vẫn có thể chia sẻ hoặc xuất Excel; nên kiểm tra lại các xung đột khi cần."
        )

    return {
        "ok": valid,
        "valid": valid,
        "reason": None if valid else "schedule_integrity_failed",
        "issue_count": issue_count,
        "message": message,
        "input_validation": input_report,
        "invalid_lesson_ids": [lesson.id for lesson in invalid_lessons],
        "count_errors": count_errors,
        "required_double_errors": required_double_errors,
        "fixed_errors": fixed_errors,
    }

def lesson_slot_error(
    db: Session,
    project: Project,
    assignment: Assignment,
    slot: int,
    exclude_lesson_id: Optional[int] = None,
    *,
    target_locked: bool = False,
):
    if slot not in all_slots(project):
        return "Ô thời khóa biểu không hợp lệ."
    if slot in parse_slots(project.blocked_slots_json):
        return "Buổi này đã bị khóa và không được xếp tiết."
    teacher = db.get(Teacher, assignment.teacher_id)
    school_class = db.get(SchoolClass, assignment.class_id)
    subject = db.get(Subject, assignment.subject_id)
    if not teacher or not school_class or not subject:
        return "Phân công không còn đầy đủ lớp, môn hoặc giáo viên."
    if slot in parse_slots(teacher.unavailable_json):
        return "Giáo viên không thể dạy ở tiết này theo ràng buộc chính thức."
    if slot in parse_slots(school_class.unavailable_json):
        return "Lớp không học ở tiết này."
    existing_lessons = db.scalars(
        select(Lesson).where(Lesson.project_id == project.id)
    ).all()
    existing_lessons = [
        lesson for lesson in existing_lessons if lesson.id != exclude_lesson_id
    ]
    existing_lessons = schedule_validation_peers(
        existing_lessons,
        target_locked=target_locked,
    )
    for lesson in existing_lessons:
        if lesson.slot != slot:
            continue
        other = db.get(Assignment, lesson.assignment_id)
        if other and (
            other.class_id == assignment.class_id
            or other.teacher_id == assignment.teacher_id
        ):
            return "Ô đích bị trùng lớp hoặc giáo viên."
    ppd = project.sessions * project.periods_per_session
    target_day = slot // ppd
    target_position = slot % ppd
    target_session = target_position // project.periods_per_session
    teacher_periods = 0
    subject_periods = []
    for lesson in existing_lessons:
        other = db.get(Assignment, lesson.assignment_id)
        if not other or lesson.slot // ppd != target_day:
            continue
        if other.teacher_id == assignment.teacher_id:
            teacher_periods += 1
        position = lesson.slot % ppd
        if (
            position // project.periods_per_session == target_session
            and other.class_id == assignment.class_id
            and other.subject_id == assignment.subject_id
        ):
            subject_periods.append(position % project.periods_per_session)
    if teacher_periods >= teacher.max_periods_day:
        return "Giáo viên đã đạt số tiết tối đa trong ngày."
    run = sorted(subject_periods + [target_position % project.periods_per_session])
    longest = current = 1
    for left, right in zip(run, run[1:]):
        current = current + 1 if right == left + 1 else 1
        longest = max(longest, current)
    if longest > subject.max_consecutive:
        return "Vượt số tiết liên tiếp tối đa của môn học."
    return None


__all__ = [name for name in globals() if not name.startswith('__')]
