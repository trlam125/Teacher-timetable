from __future__ import annotations

import json
from collections import Counter


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
    return None
