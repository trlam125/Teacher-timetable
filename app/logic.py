from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp with an explicit timezone offset."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_json_dumps(value) -> str:
    """Serialize JSON deterministically for snapshot equality checks."""
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def effective_staff_role(account_role: str | None, membership_role: str | None) -> str | None:
    """Accept a project role only while it matches the account's current role."""
    allowed = {"scheduler", "reviewer"}
    if account_role in allowed and membership_role == account_role:
        return account_role
    return None


def timetable_capacity_validation_error(
    *,
    days: int,
    sessions: int,
    periods_per_session: int,
    blocked_slots,
    teachers: dict[int, dict],
    classes: dict[int, dict],
    assignments: list[dict],
) -> str | None:
    """Detect inexpensive, mathematically certain timetable infeasibility.

    This is intentionally a necessary-condition check, not a replacement for
    the solver. It only rejects inputs when capacity is definitely too small.
    """
    try:
        days = int(days)
        sessions = int(sessions)
        periods_per_session = int(periods_per_session)
    except (TypeError, ValueError, OverflowError):
        return "Kích thước thời khóa biểu không hợp lệ."
    if days < 1 or sessions < 1 or periods_per_session < 1:
        return "Kích thước thời khóa biểu không hợp lệ."

    periods_per_day = sessions * periods_per_session
    maximum = days * periods_per_day

    def normalized_slots(values) -> set[int]:
        result = set()
        if isinstance(values, (str, bytes, dict)) or values is None:
            return result
        try:
            iterator = iter(values)
        except TypeError:
            return result
        for value in iterator:
            if isinstance(value, bool) or (
                isinstance(value, float) and not value.is_integer()
            ):
                continue
            try:
                slot = int(value)
            except (TypeError, ValueError, OverflowError):
                continue
            if 0 <= slot < maximum:
                result.add(slot)
        return result

    blocked = normalized_slots(blocked_slots)
    all_slots = set(range(maximum))
    class_totals: defaultdict[int, int] = defaultdict(int)
    teacher_totals: defaultdict[int, int] = defaultdict(int)

    normalized_assignments = []
    for item in assignments:
        try:
            assignment_id = int(item.get("id", 0))
            class_id = int(item["class_id"])
            teacher_id = int(item["teacher_id"])
            periods = int(item["periods"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return "Có phân công không đúng định dạng."
        if periods < 1:
            return f"Phân công #{assignment_id or '?'} có số tiết/tuần không hợp lệ."
        if class_id not in classes or teacher_id not in teachers:
            return f"Phân công #{assignment_id or '?'} tham chiếu lớp hoặc giáo viên không còn tồn tại."
        class_totals[class_id] += periods
        teacher_totals[teacher_id] += periods
        normalized_assignments.append((assignment_id, class_id, teacher_id, periods))

    class_available: dict[int, set[int]] = {}
    for class_id, info in classes.items():
        unavailable = normalized_slots(info.get("unavailable", ()))
        available = all_slots - blocked - unavailable
        class_available[class_id] = available
        required = class_totals.get(class_id, 0)
        if required > len(available):
            name = str(info.get("name") or f"#{class_id}")
            return (
                f"Lớp {name} cần {required} tiết nhưng chỉ còn {len(available)} "
                "ô có thể học sau các tiết khóa và tiết tránh."
            )

    teacher_available: dict[int, set[int]] = {}
    for teacher_id, info in teachers.items():
        unavailable = normalized_slots(info.get("unavailable", ()))
        available = all_slots - blocked - unavailable
        teacher_available[teacher_id] = available
        try:
            max_periods_day = int(info.get("max_periods_day", periods_per_day))
        except (TypeError, ValueError, OverflowError):
            max_periods_day = periods_per_day
        max_periods_day = max(0, max_periods_day)
        capacity = 0
        for day in range(days):
            start = day * periods_per_day
            available_today = sum(
                1 for slot in range(start, start + periods_per_day) if slot in available
            )
            capacity += min(max_periods_day, available_today)
        required = teacher_totals.get(teacher_id, 0)
        if required > capacity:
            name = str(info.get("name") or f"#{teacher_id}")
            return (
                f"Giáo viên {name} cần dạy {required} tiết nhưng năng lực tối đa "
                f"theo số tiết/ngày và các tiết tránh chỉ là {capacity} tiết."
            )

    for assignment_id, class_id, teacher_id, periods in normalized_assignments:
        common_available = class_available[class_id] & teacher_available[teacher_id]
        if periods > len(common_available):
            class_name = str(classes[class_id].get("name") or f"#{class_id}")
            teacher_name = str(teachers[teacher_id].get("name") or f"#{teacher_id}")
            return (
                f"Phân công #{assignment_id} ({class_name} – {teacher_name}) cần "
                f"{periods} tiết nhưng chỉ có {len(common_available)} ô mà cả lớp "
                "và giáo viên cùng khả dụng."
            )
    return None


def contiguous_session_group(
    slots: list[int] | set[int] | tuple[int, ...],
    target_slot: int,
    sessions: int,
    periods_per_session: int,
) -> set[int]:
    """Return the contiguous run containing target_slot within one day/session."""
    values = set(slots)
    if target_slot not in values:
        return set()
    periods_per_day = sessions * periods_per_session
    day = target_slot // periods_per_day
    inside = target_slot % periods_per_day
    session = inside // periods_per_session
    session_start = day * periods_per_day + session * periods_per_session
    session_end = session_start + periods_per_session

    group = {target_slot}
    cursor = target_slot - 1
    while cursor >= session_start and cursor in values:
        group.add(cursor)
        cursor -= 1
    cursor = target_slot + 1
    while cursor < session_end and cursor in values:
        group.add(cursor)
        cursor += 1
    return group


def required_double_removal_slots(
    slots: list[int] | set[int] | tuple[int, ...],
    target_slot: int,
    sessions: int,
    periods_per_session: int,
) -> set[int]:
    """Remove the whole adjacent block for a required-double assignment.

    A legitimate double occupies two adjacent periods in the same session. If
    legacy or manually-corrupted data contains a longer run, removing the whole
    run is safer than leaving another malformed fragment behind. An isolated
    slot (the permitted odd remainder) is removed by itself.
    """
    return contiguous_session_group(
        slots, target_slot, sessions, periods_per_session
    )


def revoke_last_teacher_profile(account) -> None:
    """Keep the login account but remove all teacher privileges and sessions."""
    account.teacher_id = None
    account.role = "pending"
    account.requested_teacher_name = None
    account.requested_project_id = None
    account.session_version = int(account.session_version or 0) + 1


def clear_teacher_identity(account) -> None:
    """Remove teacher-only identity fields before an account becomes admin."""
    account.teacher_id = None
    account.requested_teacher_name = None
    account.requested_project_id = None


def parse_integer_set(text: str | None) -> set[int]:
    """Parse a JSON array while preserving valid integers around bad items.

    Corrupt legacy data should not make every otherwise-valid slot disappear.
    Invalid JSON or a non-array JSON value still produces an empty set.
    """
    try:
        values = json.loads(text or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return set()
    if not isinstance(values, list):
        return set()

    result: set[int] = set()
    for value in values:
        if isinstance(value, bool) or (
            isinstance(value, float) and not value.is_integer()
        ):
            continue
        try:
            result.add(int(value))
        except (TypeError, ValueError, OverflowError):
            continue
    return result


def project_dimensions_validation_error(
    days: int,
    sessions: int,
    periods_per_session: int,
) -> str | None:
    """Validate timetable dimensions instead of silently clamping input."""
    if not 1 <= days <= 7:
        return "Số ngày học phải nằm trong khoảng từ 1 đến 7."
    if not 1 <= sessions <= 2:
        return "Số buổi mỗi ngày phải nằm trong khoảng từ 1 đến 2."
    if not 1 <= periods_per_session <= 8:
        return "Số tiết mỗi buổi phải nằm trong khoảng từ 1 đến 8."
    return None


def timetable_constraint_limits(
    sessions: int,
    periods_per_session: int,
) -> tuple[int, int]:
    """Return dynamic subject/teacher limits for one timetable layout."""
    subject_max = max(1, int(periods_per_session))
    teacher_max = max(1, int(sessions) * int(periods_per_session))
    return subject_max, teacher_max


def public_schedule_snapshot(snapshot: dict) -> dict:
    """Build the minimal, display-only payload for an anonymous share link."""
    empty = {
        "project": {},
        "classes": [],
        "teachers": [],
        "subjects": [],
        "assignments": [],
        "lessons": [],
    }
    if not isinstance(snapshot, dict):
        return empty

    def strict_int(value):
        if isinstance(value, bool):
            return None
        if isinstance(value, float):
            # Do not silently truncate malformed JSON numbers such as 1.9.
            if not value.is_integer():
                return None
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return None

    raw_project = snapshot.get("project", {})
    project = {}
    maximum = 0
    if isinstance(raw_project, dict):
        project_id = strict_int(raw_project.get("id"))
        if project_id is not None and project_id > 0:
            project["id"] = project_id
        project["name"] = str(raw_project.get("name", ""))[:200]
        project["school_name"] = str(raw_project.get("school_name", ""))[:200]

        days = strict_int(raw_project.get("days"))
        sessions = strict_int(raw_project.get("sessions"))
        periods = strict_int(raw_project.get("periods"))
        if days is not None and sessions is not None and periods is not None and (
            days > 0 and sessions > 0 and periods > 0
        ):
            project.update({"days": days, "sessions": sessions, "periods": periods})
            maximum = days * sessions * periods

        raw_blocked = raw_project.get("blocked_slots", [])
        blocked = []
        if isinstance(raw_blocked, (list, set, tuple)) and maximum > 0:
            blocked = sorted({
                slot
                for value in raw_blocked
                if (slot := strict_int(value)) is not None and 0 <= slot < maximum
            })
        project["blocked_slots"] = blocked

    raw_lessons = snapshot.get("lessons", [])
    lessons = []
    assignment_ids = set()
    if isinstance(raw_lessons, list) and maximum > 0:
        for item in raw_lessons:
            if not isinstance(item, dict):
                continue
            assignment_id = strict_int(item.get("assignment_id"))
            slot = strict_int(item.get("slot"))
            if (
                assignment_id is None
                or slot is None
                or assignment_id <= 0
                or not 0 <= slot < maximum
            ):
                continue
            lesson_id = strict_int(item.get("id"))
            lessons.append({
                "id": lesson_id,
                "assignment_id": assignment_id,
                "slot": slot,
            })
            assignment_ids.add(assignment_id)

    assignments = []
    class_ids = set()
    subject_ids = set()
    teacher_ids = set()
    raw_assignments = snapshot.get("assignments", [])
    if isinstance(raw_assignments, list):
        for item in raw_assignments:
            if not isinstance(item, dict):
                continue
            assignment_id = strict_int(item.get("id"))
            if assignment_id not in assignment_ids:
                continue
            class_id = strict_int(item.get("class_id"))
            subject_id = strict_int(item.get("subject_id"))
            teacher_id = strict_int(item.get("teacher_id"))
            if (
                class_id is None or class_id <= 0
                or subject_id is None or subject_id <= 0
                or teacher_id is None or teacher_id <= 0
            ):
                continue
            assignments.append({
                "id": assignment_id,
                "class_id": class_id,
                "subject_id": subject_id,
                "teacher_id": teacher_id,
                "class_name": str(item.get("class_name", ""))[:80],
                "subject_name": str(item.get("subject_name", ""))[:120],
                "subject_short": str(item.get("subject_short", ""))[:20],
                "teacher_name": str(item.get("teacher_name", ""))[:120],
                "teacher_short": str(item.get("teacher_short", ""))[:30],
            })
            class_ids.add(class_id)
            subject_ids.add(subject_id)
            teacher_ids.add(teacher_id)

    valid_assignment_ids = {item["id"] for item in assignments}
    lessons = [item for item in lessons if item["assignment_id"] in valid_assignment_ids]

    def filtered_entities(key, wanted_ids, allowed_fields):
        result = []
        rows = snapshot.get(key, [])
        if not isinstance(rows, list):
            return result
        for item in rows:
            if not isinstance(item, dict):
                continue
            entity_id = strict_int(item.get("id"))
            if entity_id not in wanted_ids:
                continue
            clean = {"id": entity_id}
            for field in allowed_fields:
                if field in item:
                    clean[field] = item[field]
            result.append(clean)
        return result

    return {
        "project": project,
        "classes": filtered_entities("classes", class_ids, ("name",)),
        "teachers": filtered_entities("teachers", teacher_ids, ("name", "short_name")),
        "subjects": filtered_entities("subjects", subject_ids, ("name", "short_name")),
        "assignments": assignments,
        "lessons": lessons,
    }


def normalize_slot_values(
    slots: list[int] | set[int] | tuple[int, ...],
    maximum: int,
    *,
    strict: bool = True,
) -> list[int]:
    """Normalize slot values and optionally reject out-of-range input."""
    if isinstance(slots, (str, bytes, dict)) or not isinstance(
        slots, (list, set, tuple)
    ):
        raise ValueError("Danh sách tiết không hợp lệ")
    if maximum < 0:
        raise ValueError("Giới hạn số tiết không hợp lệ")

    result: set[int] = set()
    for raw_slot in slots:
        if isinstance(raw_slot, bool) or (
            isinstance(raw_slot, float) and not raw_slot.is_integer()
        ):
            raise ValueError("Mỗi tiết phải là một số nguyên hợp lệ")
        try:
            slot = int(raw_slot)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Mỗi tiết phải là một số nguyên hợp lệ") from exc
        if not 0 <= slot < maximum:
            if strict:
                upper = max(0, maximum - 1)
                raise ValueError(f"Mỗi tiết phải nằm trong khoảng từ 0 đến {upper}")
            continue
        result.add(slot)
    return sorted(result)


def pop_matching_fixed_task(
    pending: list[dict],
    fixed_slot: int,
    fixed_size: int,
):
    """Remove and return the pending task represented by one fixed group."""
    expected = set(range(fixed_slot, fixed_slot + fixed_size))
    matching_indices: list[int] = []
    for index, item in enumerate(pending):
        if item["size"] != fixed_size:
            continue
        anchors = set(item.get("anchor_slots", ()))
        if anchors and not anchors.issubset(expected):
            continue
        planned_starts = item.get("candidate_starts")
        if planned_starts is not None and fixed_slot not in planned_starts:
            continue
        matching_indices.append(index)
    if not matching_indices:
        return None

    match_index = max(
        matching_indices,
        key=lambda index: bool(pending[index].get("anchor_slots", ())),
    )
    return pending.pop(match_index)


def fixed_group_validation_error(
    expected_group_sizes: list[int] | tuple[int, ...],
    fixed_groups: list[tuple[int, int]],
    *,
    days: int,
    sessions: int,
    periods_per_session: int,
) -> str | None:
    """Validate fixed rows against the assignment's allowed group pattern."""
    expected = Counter(int(size) for size in expected_group_sizes)
    used: Counter[int] = Counter()
    occupied: set[int] = set()
    normalized_groups: list[tuple[int, int]] = []
    periods_per_day = sessions * periods_per_session
    maximum = days * periods_per_day

    for raw_slot, raw_size in fixed_groups:
        try:
            slot = int(raw_slot)
            size = int(raw_size)
        except (TypeError, ValueError, OverflowError):
            return "Dữ liệu tiết cố định không hợp lệ."
        if size < 1 or expected[size] <= used[size]:
            return "Số tiết hoặc cụm cố định đã vượt số lượng của phân công."
        if slot < 0 or slot + size > maximum:
            return "Tiết cố định nằm ngoài phạm vi thời khóa biểu."
        position = slot % periods_per_day
        period = position % periods_per_session
        if period + size > periods_per_session:
            return "Cụm tiết cố định vượt qua ranh giới buổi học."
        group_slots = set(range(slot, slot + size))
        if occupied.intersection(group_slots):
            return "Các cụm tiết cố định bị trùng nhau."
        occupied.update(group_slots)
        used[size] += 1
        normalized_groups.append((slot, size))

    # Với mẫu có cụm nhiều hơn một tiết, các cụm phải được ngăn cách ít
    # nhất một tiết trong cùng buổi. Nếu không, hai cụm 2 + 2 đặt tại
    # 0-1 và 2-3 sẽ thực tế trở thành một dải 4 tiết liên tục.
    if any(size > 1 for size in expected):
        ordered = sorted(normalized_groups)
        for (left_slot, left_size), (right_slot, _right_size) in zip(
            ordered, ordered[1:]
        ):
            left_day = left_slot // periods_per_day
            left_session = (left_slot % periods_per_day) // periods_per_session
            right_day = right_slot // periods_per_day
            right_session = (right_slot % periods_per_day) // periods_per_session
            if (
                (left_day, left_session) == (right_day, right_session)
                and left_slot + left_size == right_slot
            ):
                return "Các cụm tiết cố định phải cách nhau ít nhất một tiết trong cùng buổi."
    return None


def resolve_fixed_group_size(
    expected_group_sizes: list[int] | tuple[int, ...],
    stored_size,
    inferred_sizes: list[int] | tuple[int, ...] = (),
) -> int:
    """Resolve a fixed group's size without overriding valid stored data.

    ``group_size`` is the persisted meaning of a FixedLesson row. Lesson runs
    are only a legacy recovery source when that stored value is missing or no
    longer valid for the assignment's current pattern.
    """
    expected = [int(size) for size in expected_group_sizes if int(size) > 0]
    try:
        size = int(1 if stored_size in (None, "") else stored_size)
    except (TypeError, ValueError, OverflowError):
        size = 1

    if size in expected:
        return size

    for raw_size in inferred_sizes:
        try:
            inferred = int(raw_size)
        except (TypeError, ValueError, OverflowError):
            continue
        if inferred in expected:
            return inferred
    return expected[0] if expected else 1


def fixed_lesson_coverage_error(
    fixed_groups: list[tuple[int, int]],
    lessons: list[tuple[int, bool]],
) -> str | None:
    """Check the bidirectional FixedLesson <=> locked Lesson invariant."""
    coverage: set[int] = set()
    for raw_slot, raw_size in fixed_groups:
        try:
            slot = int(raw_slot)
            size = int(raw_size)
        except (TypeError, ValueError, OverflowError):
            return "Dữ liệu tiết cố định không hợp lệ."
        if size < 1:
            return "Dữ liệu tiết cố định không hợp lệ."
        coverage.update(range(slot, slot + size))

    lesson_by_slot: dict[int, bool] = {}
    for raw_slot, raw_locked in lessons:
        try:
            slot = int(raw_slot)
        except (TypeError, ValueError, OverflowError):
            return "Dữ liệu tiết học không hợp lệ."
        if slot in lesson_by_slot:
            return "Phân công có tiết học bị trùng ô."
        if type(raw_locked) is not bool:
            return "Trạng thái khóa của tiết học không hợp lệ."
        lesson_by_slot[slot] = raw_locked

    for slot in sorted(coverage):
        if slot not in lesson_by_slot:
            return f"Tiết cố định tại ô {slot} không có tiết học tương ứng."
        if not lesson_by_slot[slot]:
            return f"Tiết cố định tại ô {slot} chưa được khóa."

    for slot, locked in lesson_by_slot.items():
        if locked and slot not in coverage:
            return f"Tiết khóa tại ô {slot} không thuộc cụm cố định nào."
    return None


def fixed_candidate_validation_error(
    expected_group_sizes: list[int] | tuple[int, ...],
    fixed_groups: list[tuple[int, int]],
    lessons: list[tuple[int, bool]],
    *,
    days: int,
    sessions: int,
    periods_per_session: int,
) -> str | None:
    """Validate the complete hypothetical fixed/locked state before mutation."""
    group_error = fixed_group_validation_error(
        expected_group_sizes,
        fixed_groups,
        days=days,
        sessions=sessions,
        periods_per_session=periods_per_session,
    )
    if group_error:
        return group_error
    return fixed_lesson_coverage_error(fixed_groups, lessons)


def schedule_change_counts(
    before: dict[int, list[int] | set[int] | tuple[int, ...]],
    after: dict[int, list[int] | set[int] | tuple[int, ...]],
    assignment_ids: set[int] | None = None,
) -> dict[str, int]:
    """Count moved, added and removed lessons between two schedules.

    A replacement of one old slot by one new slot for the same assignment is
    counted as one move. Extra unmatched slots are additions or removals.
    """
    ids = set(before) | set(after)
    if assignment_ids is not None:
        ids &= set(assignment_ids)
    moved = added = removed = changed_assignments = 0
    for assignment_id in ids:
        old_slots = set(before.get(assignment_id, ()))
        new_slots = set(after.get(assignment_id, ()))
        if old_slots == new_slots:
            continue
        changed_assignments += 1
        old_only = old_slots - new_slots
        new_only = new_slots - old_slots
        moved_here = min(len(old_only), len(new_only))
        moved += moved_here
        removed += len(old_only) - moved_here
        added += len(new_only) - moved_here
    return {
        "moved": moved,
        "added": added,
        "removed": removed,
        "changed": moved + added + removed,
        "changed_assignments": changed_assignments,
    }


def strict_snapshot_lesson_states(value) -> dict[tuple[int, int], bool]:
    """Validate lesson rows and retain their persisted lock state."""
    if not isinstance(value, list):
        raise ValueError("Danh sách tiết trong phiên bản không đúng định dạng")
    result: dict[tuple[int, int], bool] = {}
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Tiết thứ {index} trong phiên bản không đúng định dạng")
        assignment_id = item.get("assignment_id")
        slot = item.get("slot")
        locked = item.get("locked", False)
        if type(assignment_id) is not int or assignment_id < 1:
            raise ValueError(f"Mã phân công của tiết thứ {index} không hợp lệ trong phiên bản")
        if type(slot) is not int or slot < 0:
            raise ValueError(f"Ô lịch của tiết thứ {index} không hợp lệ trong phiên bản")
        if type(locked) is not bool:
            raise ValueError(f"Trạng thái khóa của tiết thứ {index} không hợp lệ trong phiên bản")
        key = (assignment_id, slot)
        if key in result:
            raise ValueError(
                f"Phiên bản chứa tiết bị trùng tại phân công {assignment_id}, ô {slot}"
            )
        result[key] = locked
    return result


def strict_snapshot_lesson_pairs(value) -> set[tuple[int, int]]:
    """Backward-compatible position-only view of validated lesson rows."""
    return set(strict_snapshot_lesson_states(value))


def strict_snapshot_fixed_groups(value) -> set[tuple[int, int, int]]:
    """Validate fixed groups from a saved schedule snapshot."""
    if value is None:
        value = []
    if not isinstance(value, list):
        raise ValueError("Danh sách cụm cố định trong phiên bản không đúng định dạng")
    result: set[tuple[int, int, int]] = set()
    starts: set[tuple[int, int]] = set()
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Cụm cố định thứ {index} trong phiên bản không đúng định dạng")
        assignment_id = item.get("assignment_id")
        slot = item.get("slot")
        group_size = item.get("group_size", 1)
        if type(assignment_id) is not int or assignment_id < 1:
            raise ValueError(f"Mã phân công của cụm cố định thứ {index} không hợp lệ")
        if type(slot) is not int or slot < 0:
            raise ValueError(f"Ô lịch của cụm cố định thứ {index} không hợp lệ")
        if type(group_size) is not int or group_size < 1:
            raise ValueError(f"Kích thước cụm cố định thứ {index} không hợp lệ")
        start_key = (assignment_id, slot)
        if start_key in starts:
            raise ValueError(
                f"Phiên bản chứa cụm cố định bị trùng tại phân công {assignment_id}, ô {slot}"
            )
        starts.add(start_key)
        result.add((assignment_id, slot, group_size))
    return result


def compare_schedule_snapshot_state(
    left_lessons,
    right_lessons,
    left_fixed_groups=None,
    right_fixed_groups=None,
) -> dict:
    """Compare positions, lock flags and fixed groups in two snapshots."""
    left_states = strict_snapshot_lesson_states(left_lessons)
    right_states = strict_snapshot_lesson_states(right_lessons)
    left_fixed = strict_snapshot_fixed_groups(
        [] if left_fixed_groups is None else left_fixed_groups
    )
    right_fixed = strict_snapshot_fixed_groups(
        [] if right_fixed_groups is None else right_fixed_groups
    )
    left_rows = set(left_states)
    right_rows = set(right_states)
    shared_rows = left_rows & right_rows
    assignment_ids = {
        assignment_id
        for assignment_id, _slot in left_rows | right_rows
    } | {
        assignment_id
        for assignment_id, _slot, _size in left_fixed | right_fixed
    }

    moved = added = removed = locked_changed = 0
    changes = []
    for assignment_id in sorted(assignment_ids):
        old_slots = sorted(slot for aid, slot in left_rows if aid == assignment_id)
        new_slots = sorted(slot for aid, slot in right_rows if aid == assignment_id)
        old_only = sorted(set(old_slots) - set(new_slots))
        new_only = sorted(set(new_slots) - set(old_slots))
        moved_here = min(len(old_only), len(new_only))
        added_here = max(0, len(new_only) - moved_here)
        removed_here = max(0, len(old_only) - moved_here)
        lock_changed_slots = sorted(
            slot for aid, slot in shared_rows
            if aid == assignment_id and left_states[(aid, slot)] != right_states[(aid, slot)]
        )
        old_locked_slots = sorted(
            slot for (aid, slot), locked in left_states.items()
            if aid == assignment_id and locked
        )
        new_locked_slots = sorted(
            slot for (aid, slot), locked in right_states.items()
            if aid == assignment_id and locked
        )
        old_fixed = sorted(
            (slot, size) for aid, slot, size in left_fixed if aid == assignment_id
        )
        new_fixed = sorted(
            (slot, size) for aid, slot, size in right_fixed if aid == assignment_id
        )
        fixed_added = sorted(set(new_fixed) - set(old_fixed))
        fixed_removed = sorted(set(old_fixed) - set(new_fixed))
        if not (old_only or new_only or lock_changed_slots or fixed_added or fixed_removed):
            continue
        moved += moved_here
        added += added_here
        removed += removed_here
        locked_changed += len(lock_changed_slots)
        changes.append({
            "assignment_id": assignment_id,
            "old_slots": old_slots,
            "new_slots": new_slots,
            "old_locked_slots": old_locked_slots,
            "new_locked_slots": new_locked_slots,
            "lock_changed_slots": lock_changed_slots,
            "old_fixed_groups": old_fixed,
            "new_fixed_groups": new_fixed,
            "fixed_added": fixed_added,
            "fixed_removed": fixed_removed,
            "moved": moved_here,
            "added": added_here,
            "removed": removed_here,
        })

    fixed_added_count = len(right_fixed - left_fixed)
    fixed_removed_count = len(left_fixed - right_fixed)
    return {
        "left_lesson_count": len(left_rows),
        "right_lesson_count": len(right_rows),
        "left_fixed_count": len(left_fixed),
        "right_fixed_count": len(right_fixed),
        "summary": {
            # same_position chỉ xét vị trí; unchanged còn yêu cầu trạng thái
            # locked không đổi. Giữ cả hai trường để API không còn nhập nhằng.
            "same_position": len(shared_rows),
            "unchanged": len(shared_rows) - locked_changed,
            "moved": moved,
            "added": added,
            "removed": removed,
            "locked_changed": locked_changed,
            "fixed_added": fixed_added_count,
            "fixed_removed": fixed_removed_count,
            "fixed_changed": fixed_added_count + fixed_removed_count,
            "changed_assignments": len(changes),
        },
        "changes": changes,
    }


def strict_snapshot_assignment_map(value) -> dict[int, dict]:
    """Validate assignment metadata used by schedule-version comparison."""
    if not isinstance(value, list):
        raise ValueError("Danh sách phân công trong phiên bản không đúng định dạng")
    result: dict[int, dict] = {}
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Phân công thứ {index} trong phiên bản không đúng định dạng")
        assignment_id = item.get("id")
        if type(assignment_id) is not int or assignment_id < 1:
            raise ValueError(f"Mã phân công thứ {index} không hợp lệ trong phiên bản")
        if assignment_id in result:
            raise ValueError(f"Phiên bản chứa mã phân công {assignment_id} bị trùng")
        result[assignment_id] = item
    return result
