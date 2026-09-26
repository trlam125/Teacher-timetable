from __future__ import annotations

from collections import Counter, defaultdict

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logic import fixed_group_validation_error, normalize_slot_values, parse_integer_set
from app.models import (
    Assignment, FixedLesson, Lesson, Project, SchoolClass, Subject, Teacher,
)

BLOCK_MODES = {"free", "preferred_double", "required_double"}

def slot_meta(project: Project, slot: int):
    ppd = project.sessions * project.periods_per_session
    day = slot // ppd
    inside = slot % ppd
    session = inside // project.periods_per_session
    period = inside % project.periods_per_session
    return day, session, period

def all_slots(project: Project):
    return list(range(project.days * project.sessions * project.periods_per_session))

def parse_slots(text: str):
    return parse_integer_set(text)

def consecutive_groups(pattern: str, total_periods: int):
    """Đọc mẫu cụm cũ, chỉ dùng cho migration/tương thích dữ liệu cũ."""
    text = (pattern or "").strip()
    if not text:
        return [1] * total_periods
    try:
        groups = [int(value.strip()) for value in text.split(",") if value.strip()]
    except ValueError as exc:
        raise ValueError("Mẫu tiết liên tiếp cũ không hợp lệ.") from exc
    if not groups or any(value < 1 for value in groups) or sum(groups) != total_periods:
        raise ValueError("Mẫu tiết liên tiếp cũ không hợp lệ.")
    return groups

def required_double_structure_feasible(
    project: Project, total_periods: int, max_consecutive: int
) -> bool:
    """Kiểm tra khả năng xếp required_double chỉ theo cấu trúc thời khóa biểu.

    Hàm này không cần giáo viên/lớp cụ thể nên dùng được khi lưu chương trình
    môn của khối. Nó bảo đảm các cặp 2 tiết (và 1 tiết lẻ nếu có) có thể
    phân bố qua các buổi mà không vượt ``max_consecutive``.
    """
    total = max(0, int(total_periods or 0))
    target_doubles = total // 2
    target_singles = total % 2
    if target_doubles == 0 and target_singles == 0:
        return True

    pps = int(project.periods_per_session)
    session_count = int(project.days) * int(project.sessions)
    max_run = max(1, int(max_consecutive or 1))
    if target_doubles and (pps < 2 or max_run < 2):
        return False

    memo: dict[tuple[int, int], set[tuple[int, int]]] = {}

    def session_walk(period: int, current_run: int) -> set[tuple[int, int]]:
        if period >= pps:
            return {(0, 0)}
        key = (period, current_run)
        if key in memo:
            return memo[key]

        # Để trống một tiết sẽ cắt chuỗi liên tiếp của môn.
        options = set(session_walk(period + 1, 0))

        if target_singles and current_run + 1 <= max_run:
            for doubles, singles in session_walk(period + 1, current_run + 1):
                if singles < target_singles:
                    options.add((doubles, singles + 1))

        if (
            target_doubles
            and period + 1 < pps
            and current_run + 2 <= max_run
        ):
            for doubles, singles in session_walk(period + 2, current_run + 2):
                if doubles < target_doubles:
                    options.add((doubles + 1, singles))

        memo[key] = {
            (min(d, target_doubles), min(s, target_singles))
            for d, s in options
            if d <= target_doubles and s <= target_singles
        }
        return memo[key]

    session_options = session_walk(0, 0)
    reachable = {(0, 0)}
    for _ in range(session_count):
        next_reachable = set(reachable)
        for current_d, current_s in reachable:
            for add_d, add_s in session_options:
                doubles = current_d + add_d
                singles = current_s + add_s
                if doubles <= target_doubles and singles <= target_singles:
                    next_reachable.add((doubles, singles))
        reachable = next_reachable

    return (target_doubles, target_singles) in reachable


def normalized_block_mode(
    value: str, total_periods: int, subject: Subject, project: Project
):
    mode = (value or "free").strip().lower()
    aliases = {
        "prefer_double": "preferred_double",
        "preferred": "preferred_double",
        "required": "required_double",
        "double": "required_double",
    }
    mode = aliases.get(mode, mode)
    if mode not in BLOCK_MODES:
        raise ValueError("Chế độ xếp tiết không hợp lệ.")
    total_slots = project.days * project.sessions * project.periods_per_session
    if total_periods > total_slots:
        raise ValueError(
            f"Số tiết/tuần không được vượt quá {total_slots} ô của thời khóa biểu."
        )
    if mode in {"preferred_double", "required_double"} and total_periods >= 2:
        if subject.max_consecutive < 2:
            raise ValueError(
                f"Môn {subject.name} đang giới hạn tối đa {subject.max_consecutive} tiết liên tiếp; "
                "hãy tăng giới hạn lên ít nhất 2 trước khi chọn chế độ tiết đôi."
            )
        if project.periods_per_session < 2:
            raise ValueError("Mỗi buổi phải có ít nhất 2 tiết để dùng chế độ tiết đôi.")
    if mode == "required_double":
        groups = [2] * (total_periods // 2) + ([1] if total_periods % 2 else [])
        if not timetable_pattern_feasible(project, groups):
            raise ValueError(
                "Số cặp tiết bắt buộc không thể phân bố trong số ngày, buổi và tiết hiện có."
            )
        if not required_double_structure_feasible(
            project, total_periods, subject.max_consecutive
        ):
            raise ValueError(
                f"Không thể phân bố {total_periods} tiết bắt buộc theo cặp mà vẫn giữ "
                f"tối đa {subject.max_consecutive} tiết liên tiếp trong mỗi buổi. "
                "Hãy giảm số tiết/tuần, tăng giới hạn tiết liên tiếp hoặc đổi chế độ xếp tiết."
            )
    return mode

def assignment_requires_double(assignment: Assignment):
    return getattr(assignment, "block_mode", "free") == "required_double"

def assignment_prefers_double(assignment: Assignment):
    return getattr(assignment, "block_mode", "free") == "preferred_double"

def assignment_groups(assignment: Assignment):
    total = max(0, int(assignment.periods_per_week or 0))
    if assignment_requires_double(assignment):
        return [2] * (total // 2) + ([1] if total % 2 else [])
    return [1] * total

def required_double_block_state(
    project: Project,
    assignment: Assignment,
    lessons: list[Lesson],
):
    """Validate persisted required-double blocks without inferring adjacency."""
    expected = Counter(assignment_groups(assignment))
    groups = defaultdict(list)
    for lesson in lessons:
        block_id = getattr(lesson, "block_id", None)
        if not block_id:
            return {"valid": False, "reason": "Tiết học chưa có block_id.", "groups": [], "missing_sizes": []}
        groups[block_id].append(lesson)

    used = Counter()
    normalized = []
    for block_id, members in groups.items():
        members = sorted(members, key=lambda row: row.slot)
        declared_sizes = {int(getattr(row, "block_size", 1) or 1) for row in members}
        if len(declared_sizes) != 1:
            return {
                "valid": False,
                "reason": f"Block {block_id} có metadata kích thước không thống nhất.",
                "groups": [],
                "missing_sizes": [],
            }
        size = declared_sizes.pop()
        if size not in expected or len(members) != size:
            return {
                "valid": False,
                "reason": f"Block {block_id} cần {size} tiết nhưng hiện có {len(members)} tiết.",
                "groups": [],
                "missing_sizes": [],
            }
        if size == 2:
            first, second = members
            first_meta = slot_meta(project, first.slot)
            second_meta = slot_meta(project, second.slot)
            if first_meta[:2] != second_meta[:2] or second.slot != first.slot + 1:
                return {
                    "valid": False,
                    "reason": "Một block tiết đôi không nằm cùng ngày/buổi và liên tiếp.",
                    "groups": [],
                    "missing_sizes": [],
                }
        used[size] += 1
        if used[size] > expected[size]:
            return {
                "valid": False,
                "reason": "Số block đã xếp vượt cấu trúc required_double của phân công.",
                "groups": [],
                "missing_sizes": [],
            }
        normalized.append({
            "block_id": block_id,
            "size": size,
            "start": members[0].slot,
            "lessons": members,
        })

    missing = []
    for size in (2, 1):
        missing.extend([size] * max(0, expected[size] - used[size]))
    return {"valid": True, "reason": "", "groups": normalized, "missing_sizes": missing}


def next_required_double_block_size(
    project: Project,
    assignment: Assignment,
    lessons: list[Lesson],
) -> int | None:
    state = required_double_block_state(project, assignment, lessons)
    if not state["valid"]:
        return None
    missing = state["missing_sizes"]
    return int(missing[0]) if missing else 0


def required_double_hard_feasible(
    project: Project,
    teacher: Teacher,
    school_class: SchoolClass,
    total_periods: int,
    *,
    max_periods_day: int | None = None,
    teacher_unavailable_slots: set[int] | None = None,
    class_unavailable_slots: set[int] | None = None,
    project_blocked_slots: set[int] | None = None,
    max_consecutive: int | None = None,
) -> bool:
    """Kiểm tra sớm mẫu required_double chỉ với các ràng buộc cứng.

    Khác kiểm tra capacity theo tuần, hàm này chứng minh rằng số cặp 2 tiết
    thực sự có thể đặt vào các ô còn dùng được, không vượt giới hạn
    tiết/ngày và không tạo chuỗi môn dài hơn ``max_consecutive``. Các cặp
    vẫn được phép nằm sát nhau khi giới hạn liên tiếp của môn cho phép.
    """
    total = max(0, int(total_periods or 0))
    target_doubles = total // 2
    target_singles = total % 2
    if target_doubles == 0 and target_singles == 0:
        return True

    daily_limit = int(
        max_periods_day if max_periods_day is not None else teacher.max_periods_day
    )
    if target_doubles and daily_limit < 2:
        return False

    maximum = project.days * project.sessions * project.periods_per_session
    project_blocked = (
        set(project_blocked_slots)
        if project_blocked_slots is not None
        else set(
            valid_slots(project, parse_slots(project.blocked_slots_json), strict=False)
        )
    )
    teacher_blocked = (
        set(teacher_unavailable_slots)
        if teacher_unavailable_slots is not None
        else set(
            valid_slots(project, parse_slots(teacher.unavailable_json), strict=False)
        )
    )
    class_blocked = (
        set(class_unavailable_slots)
        if class_unavailable_slots is not None
        else set(
            valid_slots(
                project, parse_slots(school_class.unavailable_json), strict=False
            )
        )
    )
    blocked = {
        slot
        for slot in project_blocked | teacher_blocked | class_blocked
        if 0 <= slot < maximum
    }

    ppd = project.sessions * project.periods_per_session
    pps = project.periods_per_session
    max_run = max(1, int(max_consecutive if max_consecutive is not None else pps))
    if target_doubles and max_run < 2:
        return False

    def session_options(day: int, session: int):
        base = day * ppd + session * pps
        allowed = [base + period not in blocked for period in range(pps)]
        memo = {}

        def walk(period: int, current_run: int):
            if period >= pps:
                return {(0, 0)}
            key = (period, current_run)
            if key in memo:
                return memo[key]

            # Bỏ trống tiết hiện tại sẽ cắt chuỗi liên tiếp của môn.
            options = set(walk(period + 1, 0))
            if allowed[period] and current_run + 1 <= max_run:
                for doubles, singles in walk(period + 1, current_run + 1):
                    if singles < 1:
                        options.add((doubles, singles + 1))
            if (
                period + 1 < pps
                and allowed[period]
                and allowed[period + 1]
                and current_run + 2 <= max_run
            ):
                for doubles, singles in walk(period + 2, current_run + 2):
                    options.add((doubles + 1, singles))
            memo[key] = options
            return options

        return {
            (min(d, target_doubles), min(s, target_singles))
            for d, s in walk(0, 0)
            if d <= target_doubles and s <= target_singles
        }

    day_options = []
    for day in range(project.days):
        combined = {(0, 0)}
        for session in range(project.sessions):
            next_options = set()
            for left_d, left_s in combined:
                for right_d, right_s in session_options(day, session):
                    doubles = left_d + right_d
                    singles = left_s + right_s
                    if doubles <= target_doubles and singles <= target_singles:
                        next_options.add((doubles, singles))
            combined = next_options
        day_options.append({(d, s) for d, s in combined if 2 * d + s <= daily_limit})

    reachable = {(0, 0)}
    for options in day_options:
        next_reachable = set(reachable)
        for current_d, current_s in reachable:
            for add_d, add_s in options:
                doubles = current_d + add_d
                singles = current_s + add_s
                if doubles <= target_doubles and singles <= target_singles:
                    next_reachable.add((doubles, singles))
        reachable = next_reachable
    return (target_doubles, target_singles) in reachable

def ensure_required_double_hard_feasible(
    project: Project,
    teacher: Teacher,
    school_class: SchoolClass,
    subject: Subject,
    total_periods: int,
    mode: str,
    *,
    max_periods_day: int | None = None,
    teacher_unavailable_slots: set[int] | None = None,
    class_unavailable_slots: set[int] | None = None,
    project_blocked_slots: set[int] | None = None,
    max_consecutive: int | None = None,
) -> None:
    if mode != "required_double":
        return
    daily_limit = int(
        max_periods_day if max_periods_day is not None else teacher.max_periods_day
    )
    if total_periods >= 2 and daily_limit < 2:
        raise HTTPException(
            409,
            f"Không thể dùng bắt buộc tiết đôi cho {school_class.name} – {subject.name}: "
            f"{teacher.name} chỉ được dạy tối đa {daily_limit} tiết/ngày. "
            "Cần ít nhất 2 tiết/ngày để xếp một cặp tiết.",
        )
    effective_max_consecutive = int(
        subject.max_consecutive if max_consecutive is None else max_consecutive
    )
    if not required_double_hard_feasible(
        project,
        teacher,
        school_class,
        total_periods,
        max_periods_day=max_periods_day,
        teacher_unavailable_slots=teacher_unavailable_slots,
        class_unavailable_slots=class_unavailable_slots,
        project_blocked_slots=project_blocked_slots,
        max_consecutive=effective_max_consecutive,
    ):
        raise HTTPException(
            409,
            f"Không thể xếp đủ các cặp tiết bắt buộc cho {school_class.name} – {subject.name} "
            f"với {teacher.name} theo tiết tránh, buổi/tiết khóa, giới hạn tiết/ngày "
            f"và tối đa {effective_max_consecutive} tiết liên tiếp của môn.",
        )

def ensure_assignment_hard_feasible(
    project: Project,
    teacher: Teacher,
    school_class: SchoolClass,
    subject: Subject,
    total_periods: int,
    mode: str,
    *,
    max_periods_day: int | None = None,
    teacher_unavailable_slots: set[int] | None = None,
    class_unavailable_slots: set[int] | None = None,
    project_blocked_slots: set[int] | None = None,
    max_consecutive: int | None = None,
) -> None:
    """Validate common availability for every mode, independent of movable lessons."""
    if mode == "required_double":
        return ensure_required_double_hard_feasible(
            project, teacher, school_class, subject, total_periods, mode,
            max_periods_day=max_periods_day,
            teacher_unavailable_slots=teacher_unavailable_slots,
            class_unavailable_slots=class_unavailable_slots,
            project_blocked_slots=project_blocked_slots,
            max_consecutive=max_consecutive,
        )

    blocked = set()
    for override, stored in (
        (teacher_unavailable_slots, teacher.unavailable_json),
        (class_unavailable_slots, school_class.unavailable_json),
        (project_blocked_slots, project.blocked_slots_json),
    ):
        blocked.update(parse_slots(stored) if override is None else override)
    daily_limit = int(teacher.max_periods_day if max_periods_day is None else max_periods_day)
    run_limit = max(1, int(subject.max_consecutive if max_consecutive is None else max_consecutive))
    pps = project.periods_per_session
    capacity = 0
    for day in range(project.days):
        day_capacity = 0
        for session in range(project.sessions):
            base = (day * project.sessions + session) * pps
            run = 0
            for period in range(pps + 1):
                if period < pps and base + period not in blocked:
                    run += 1
                else:
                    # Each run_limit+1 usable slots needs one gap in this subject.
                    day_capacity += run - run // (run_limit + 1)
                    run = 0
        capacity += min(max(0, daily_limit), day_capacity)
    if total_periods > capacity:
        raise HTTPException(
            409,
            f"Không thể phân công {school_class.name} – {subject.name} cho {teacher.name}: "
            f"cần {total_periods} tiết/tuần nhưng các ô cùng khả dụng chỉ cho phép "
            f"tối đa {capacity} tiết theo tiết tránh, khóa lịch và giới hạn tiết. "
            "Hãy điều chỉnh ràng buộc hoặc giảm số tiết.",
        )

def assignment_generated_pattern(assignment: Assignment):
    return (
        ",".join(str(value) for value in assignment_groups(assignment))
        if assignment_requires_double(assignment)
        else ""
    )

def valid_slots(
    project: Project,
    slots: list[int] | set[int] | tuple[int, ...],
    *,
    strict: bool = True,
):
    """Chuẩn hóa slot; dữ liệu API sai phạm vi phải bị từ chối rõ ràng."""
    maximum = project.days * project.sessions * project.periods_per_session
    try:
        return normalize_slot_values(slots, maximum, strict=strict)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

def bounded_int(value, default: int, minimum: int, maximum: int, label: str):
    raw = default if value in (None, "") else value
    if isinstance(raw, bool) or isinstance(raw, float) and not raw.is_integer():
        raise HTTPException(
            400, f"{label} phải là số nguyên từ {minimum} đến {maximum}"
        )
    try:
        parsed = int(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            400, f"{label} phải là số nguyên từ {minimum} đến {maximum}"
        ) from exc
    if not minimum <= parsed <= maximum:
        raise HTTPException(
            400, f"{label} phải nằm trong khoảng từ {minimum} đến {maximum}"
        )
    return parsed

def pattern_slots_match(
    project: Project, pattern: str, total_periods: int, slots: list[int] | set[int]
):
    """Kiểm tra các cụm tiết thực tế có đúng mẫu đã khai báo hay không."""
    try:
        expected = sorted(consecutive_groups(pattern, total_periods))
    except ValueError:
        return False
    if len(slots) != total_periods:
        return False
    ppd = project.sessions * project.periods_per_session
    groups = defaultdict(list)
    for slot in sorted(set(slots)):
        day = slot // ppd
        inside = slot % ppd
        session = inside // project.periods_per_session
        period = inside % project.periods_per_session
        groups[(day, session)].append(period)
    actual = []
    for periods in groups.values():
        run = 1
        for left, right in zip(periods, periods[1:]):
            if right == left + 1:
                run += 1
            else:
                actual.extend([2] * (run // 2))
                if run % 2:
                    actual.append(1)
                run = 1
        actual.extend([2] * (run // 2))
        if run % 2:
            actual.append(1)
    return sorted(actual) == expected

def assignment_run_groups(project: Project, slots: list[int] | set[int]):
    """Trả về các cụm liên tiếp theo đúng ranh giới ngày và buổi."""
    grouped = defaultdict(list)
    for slot in sorted(set(slots)):
        day, session, period = slot_meta(project, slot)
        grouped[(day, session)].append((period, slot))
    runs = []
    for values in grouped.values():
        current = [values[0]] if values else []
        for item in values[1:]:
            if item[0] == current[-1][0] + 1:
                current.append(item)
            else:
                runs.append(
                    {
                        "start": current[0][1],
                        "size": len(current),
                        "slots": [x[1] for x in current],
                    }
                )
                current = [item]
        if current:
            runs.append(
                {
                    "start": current[0][1],
                    "size": len(current),
                    "slots": [x[1] for x in current],
                }
            )
    return sorted(runs, key=lambda item: item["start"])

def preferred_double_pair_count(project: Project, slots: list[int] | set[int]):
    """Đếm các cụm đúng 2 tiết cho chế độ ưu tiên tiết đôi.

    Cụm 3 hoặc 4 tiết liên tiếp không được tách ngầm thành các cặp ảo. Điều này
    giữ cách chấm điểm của solver đồng nhất với cách giao diện đánh dấu tiết đôi.
    """
    return sum(1 for run in assignment_run_groups(project, slots) if run["size"] == 2)

def _pack_pattern_groups_into_segments(
    group_sizes: list[int], segments: list[tuple[int, int]]
):
    """Xếp các cụm chưa neo vào những đoạn trống; các cụm được phép nằm sát nhau."""
    items = sorted((int(size) for size in group_sizes), reverse=True)
    if not items:
        return []
    usable = [(start, length) for start, length in segments if length > 0]
    capacities = [length for _start, length in usable]
    if sum(items) > sum(capacities):
        return None
    allocations = [[] for _segment in usable]
    failed = set()

    def search(index: int):
        if index == len(items):
            return True
        state = (index, tuple(sorted(capacities, reverse=True)))
        if state in failed:
            return False
        size = items[index]
        weight = size
        seen_capacities = set()
        for segment_index, capacity in enumerate(capacities):
            if capacity < weight or capacity in seen_capacities:
                continue
            seen_capacities.add(capacity)
            capacities[segment_index] -= weight
            allocations[segment_index].append(size)
            if search(index + 1):
                return True
            allocations[segment_index].pop()
            capacities[segment_index] += weight
        failed.add(state)
        return False

    if not search(0):
        return None
    placements = []
    for (segment_start, _length), sizes in zip(usable, allocations):
        cursor = segment_start
        for size in sizes:
            placements.append((size, cursor))
            cursor += size
    return placements

def _complete_pattern_placement(
    project: Project,
    expected: list[int],
    slots: list[int] | set[int],
    forced_placements: list[tuple[int, int]] | None = None,
):
    """Tìm một cách đặt đầy đủ các cụm, đồng thời chứa chính xác các tiết đã có."""
    values = list(slots)
    current = set(values)
    maximum = project.days * project.sessions * project.periods_per_session
    if len(values) != len(current) or any(
        slot < 0 or slot >= maximum for slot in current
    ):
        return None
    if len(current) > sum(expected) or any(
        size < 1 or size > project.periods_per_session for size in expected
    ):
        return None

    ppd = project.sessions * project.periods_per_session
    periods_per_session = project.periods_per_session
    starts_by_size = {}
    for size in set(expected):
        starts = []
        for day in range(project.days):
            for session in range(project.sessions):
                base = day * ppd + session * periods_per_session
                starts.extend(
                    base + period for period in range(periods_per_session - size + 1)
                )
        starts_by_size[size] = starts

    def interval(start: int, size: int):
        return set(range(start, start + size))

    def compatible(left_start: int, left_size: int, right_start: int, right_size: int):
        left_slots = interval(left_start, left_size)
        right_slots = interval(right_start, right_size)
        if left_slots.intersection(right_slots):
            return False
        return True

    def free_segments(selected: list[tuple[int, int, set[int]]]):
        forbidden = defaultdict(set)
        for size, start, _covered in selected:
            day, session, period = slot_meta(project, start)
            key = (day, session)
            forbidden[key].update(range(period, period + size))
        result = []
        for day in range(project.days):
            for session in range(project.sessions):
                blocked = forbidden[(day, session)]
                base = day * ppd + session * periods_per_session
                start = None
                for period in range(periods_per_session + 1):
                    is_free = period < periods_per_session and period not in blocked
                    if is_free and start is None:
                        start = period
                    elif not is_free and start is not None:
                        result.append((base + start, period - start))
                        start = None
        return result

    remaining = Counter(expected)
    selected = []
    forced_covered = set()
    for size, start in forced_placements or []:
        if remaining[size] <= 0 or start not in starts_by_size.get(size, []):
            return None
        covered = current.intersection(interval(start, size))
        if forced_covered.intersection(covered):
            return None
        if any(
            not compatible(start, size, other_start, other_size)
            for other_size, other_start, _ in selected
        ):
            return None
        remaining[size] -= 1
        selected.append((size, start, set(covered)))
        forced_covered.update(covered)
    failed = set()

    def search(uncovered: frozenset[int]):
        state = (
            tuple(sorted(uncovered)),
            tuple(sorted(remaining.items())),
            tuple(sorted((size, start) for size, start, _covered in selected)),
        )
        if state in failed:
            return None
        if not uncovered:
            rest = []
            for size, count in remaining.items():
                rest.extend([size] * count)
            packed = _pack_pattern_groups_into_segments(rest, free_segments(selected))
            if packed is None:
                failed.add(state)
                return None
            return [*selected, *[(size, start, set()) for size, start in packed]]

        target = min(uncovered)
        for size in sorted(
            (value for value, count in remaining.items() if count > 0), reverse=True
        ):
            for start in starts_by_size[size]:
                target_slots = interval(start, size)
                covered = current.intersection(target_slots)
                if target not in covered or not covered.issubset(uncovered):
                    continue
                if any(
                    not compatible(start, size, other_start, other_size)
                    for other_size, other_start, _ in selected
                ):
                    continue
                remaining[size] -= 1
                selected.append((size, start, set(covered)))
                result = search(frozenset(set(uncovered) - covered))
                if result is not None:
                    return result
                selected.pop()
                remaining[size] += 1
        failed.add(state)
        return None

    return search(frozenset(current - forced_covered))

def timetable_pattern_feasible(project: Project, groups: list[int]):
    return _complete_pattern_placement(project, groups, set()) is not None

def pattern_completion_plan(
    project: Project, assignment: Assignment, slots: list[int] | set[int],
    *, fixed_groups: list[tuple[int, int]] | None = None,
):
    """Lập kế hoạch hoàn thành mẫu tiết từ phần lịch hiện có.

    Các tiết đã đặt có thể là một đoạn liền hoặc nhiều mảnh của cùng một cụm
    (ví dụ đã có tiết 1 và 3 của cụm 3 tiết). Hàm tìm cách bao phủ toàn bộ các
    tiết hiện có bằng những cụm hợp lệ, rồi trả về phần còn thiếu của mỗi cụm.
    """
    current = set(slots)
    maximum = project.days * project.sessions * project.periods_per_session
    if len(current) != len(list(slots)) or len(current) > assignment.periods_per_week:
        return None
    if any(slot < 0 or slot >= maximum for slot in current):
        return None
    if not assignment_requires_double(assignment):
        return [
            {
                "size": 1,
                "anchor_slots": tuple(),
                "candidate_starts": None,
            }
            for _ in range(assignment.periods_per_week - len(current))
        ]
    expected = assignment_groups(assignment)
    # Consume explicit pins before deciding whether an existing lesson is a
    # single or half of a pair. Otherwise a pinned single can be reinterpreted
    # as a pair and the solver incorrectly declares a feasible project invalid.
    fixed = [(size, start) for start, size in (fixed_groups or [])]
    if fixed_group_validation_error(
        expected, fixed_groups or [], days=project.days,
        sessions=project.sessions, periods_per_session=project.periods_per_session,
    ):
        return None
    placements = _complete_pattern_placement(project, expected, current, fixed)
    if placements is None:
        return None
    ppd = project.sessions * project.periods_per_session
    plan = []
    for target_size, start, covered in placements:
        if not covered:
            plan.append(
                {
                    "size": target_size,
                    "anchor_slots": tuple(),
                    "candidate_starts": (start,) if (target_size, start) in fixed else None,
                }
            )
            continue
        if len(covered) == target_size:
            continue
        if (target_size, start) in fixed:
            plan.append({
                "size": target_size,
                "anchor_slots": tuple(sorted(covered)),
                "candidate_starts": (start,),
            })
            continue
        alternative_starts = []
        for day in range(project.days):
            for session in range(project.sessions):
                base = day * ppd + session * project.periods_per_session
                for period in range(project.periods_per_session - target_size + 1):
                    candidate = base + period
                    candidate_slots = set(range(candidate, candidate + target_size))
                    if current.intersection(candidate_slots) != covered:
                        continue
                    # Chỉ ép candidate của chính cụm đang xét. Các cụm neo còn
                    # lại phải được phép tự chọn lại vị trí; nếu ghim chúng theo
                    # một nghiệm tạm thời, ta có thể loại nhầm một candidate mà
                    # thực tế thuộc một nghiệm hoàn chỉnh khác.
                    if (
                        _complete_pattern_placement(
                            project, expected, slots, [*fixed, (target_size, candidate)]
                        )
                        is not None
                    ):
                        alternative_starts.append(candidate)
        plan.append(
            {
                "size": target_size,
                "anchor_slots": tuple(sorted(covered)),
                "candidate_starts": tuple(sorted(set(alternative_starts or [start]))),
            }
        )
    return plan

def remaining_pattern_groups(
    project: Project, assignment: Assignment, slots: list[int] | set[int]
):
    """Trả về kích thước đầy đủ của các cụm còn phải hoàn thành."""
    plan = pattern_completion_plan(project, assignment, slots)
    if plan is None:
        return None
    return [item["size"] for item in plan]

def assignment_pattern_matches(
    project: Project, assignment: Assignment, slots: list[int] | set[int]
):
    values = list(slots)
    if len(values) != len(set(values)) or len(values) != assignment.periods_per_week:
        return False
    if not assignment_requires_double(assignment):
        return True
    return pattern_slots_match(
        project,
        assignment_generated_pattern(assignment),
        assignment.periods_per_week,
        values,
    )

def fixed_row_size(
    project: Project,
    assignment: Assignment,
    row: FixedLesson,
    lessons: list[Lesson] | None = None,
) -> int:
    if not assignment_requires_double(assignment):
        return 1
    expected = assignment_groups(assignment)
    size = int(getattr(row, "group_size", 1) or 1)

    # Persisted sizes are authoritative, including a deliberately pinned single.
    # Legacy ambiguous rows must be unpinned explicitly, never silently expanded.
    if size in expected:
        return size
    return 0
