from __future__ import annotations

import json
from collections import Counter


def remap_slot_for_session_expansion(
    slot: int,
    *,
    old_sessions: int,
    new_sessions: int,
    periods_per_session: int,
) -> int:
    """Preserve day/session/period coordinates when the day gains sessions."""
    if old_sessions < 1 or new_sessions < old_sessions or periods_per_session < 1:
        raise ValueError("Cấu hình số buổi/tiết không hợp lệ")
    if isinstance(slot, bool):
        raise ValueError("Slot phải là số nguyên")
    try:
        value = int(slot)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Slot phải là số nguyên") from exc

    old_periods_per_day = old_sessions * periods_per_session
    new_periods_per_day = new_sessions * periods_per_session
    day = value // old_periods_per_day
    inside_day = value % old_periods_per_day
    session = inside_day // periods_per_session
    period = inside_day % periods_per_session
    return day * new_periods_per_day + session * periods_per_session + period


def remap_slots_for_session_expansion(
    slots: list[int] | set[int] | tuple[int, ...],
    *,
    old_sessions: int,
    new_sessions: int,
    periods_per_session: int,
) -> list[int]:
    """Remap slot collections without changing their timetable coordinates."""
    return sorted({
        remap_slot_for_session_expansion(
            slot,
            old_sessions=old_sessions,
            new_sessions=new_sessions,
            periods_per_session=periods_per_session,
        )
        for slot in slots
    })


def schedule_validation_peers(existing_lessons, *, target_locked: bool):
    """Locked lessons are validated against other locked lessons first.

    Unlocked rows are allowed to lose conflicts against a locked row because they
    can be removed/rebuilt. This prevents a stale movable lesson from making a
    valid fixed lesson look invalid.
    """
    if not target_locked:
        return list(existing_lessons)
    return [lesson for lesson in existing_lessons if bool(getattr(lesson, "locked", False))]


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
    fixed_intervals: list[tuple[int, int]] = []
    requires_separate_groups = any(size > 1 for size in expected)
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
        if requires_separate_groups:
            group_end = slot + size
            group_session = slot // periods_per_session
            for other_start, other_end in fixed_intervals:
                other_session = other_start // periods_per_session
                if group_session != other_session:
                    continue
                if group_end == other_start or other_end == slot:
                    return "Các cụm tiết cố định bắt buộc phải cách nhau ít nhất một tiết trong cùng buổi học."
        occupied.update(group_slots)
        fixed_intervals.append((slot, slot + size))
        used[size] += 1
    return None
