"""Evidence-based, teacher-friendly context for the public timetable assistant.

The provider should not be asked to infer Vietnamese school concepts from raw
ORM/JSON field names. Keep IDs here only for joining records; never send them
as part of the teacher-facing narrative.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

MODE_LABELS = {
    "free": "Xếp tiết linh hoạt",
    "preferred_double": "Ưu tiên xếp hai tiết liền nhau",
    "required_double": "Bắt buộc xếp hai tiết liền nhau thành cặp",
    "max_two_consecutive": "Mỗi buổi có nhiều nhất hai tiết của môn này; nếu có hai tiết thì phải liền nhau",
}

_DAY_NAMES = ("Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ nhật")


def _items(value: Any) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result


def _by_id(records: list[dict]) -> dict[int, dict]:
    return {ident: row for row in records if (ident := _safe_int(row.get("id"))) is not None}


def _label(row: dict | None, key: str = "name") -> str:
    if not row:
        return "Chưa xác định"
    return str(row.get(key) or "Chưa xác định").strip()[:180]


def _mode(mode: Any) -> str:
    return MODE_LABELS.get(str(mode or "free"), "Chế độ chưa xác định (cần kiểm tra lại)")


def _slot_text(slot: Any, days: int, sessions: int, periods: int) -> str | None:
    value = _safe_int(slot)
    if value is None or days <= 0 or sessions <= 0 or periods <= 0:
        return None
    per_day = sessions * periods
    if not (0 <= value < days * per_day):
        return None
    day = value // per_day
    session = (value % per_day) // periods
    period = (value % periods) + 1
    day_name = _DAY_NAMES[day] if day < len(_DAY_NAMES) else f"Ngày {day+1}"
    session_name = "Cả buổi" if sessions == 1 else ("Sáng" if session == 0 else "Chiều" if session == 1 else f"Buổi {session + 1}")
    return f"{day_name}, buổi {session_name.lower()}, tiết {period}"


def build_teacher_context(data: dict[str, Any]) -> dict[str, Any]:
    """Convert known project structure to Vietnamese + computed, scoped facts.

    No 'null', 'free', IDs, snake_case keys, or unsupported blanket quality
    claims should be present in the context sent to the assistant.
    """
    data = data if isinstance(data, dict) else {}
    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    days = _safe_int(project.get("days")) or 0
    sessions = _safe_int(project.get("sessions")) or 0
    periods = _safe_int(project.get("periods")) or 0

    subjects = _items(data.get("subjects"))
    teachers = _items(data.get("teachers"))
    grades = _items(data.get("grades"))
    classes = _items(data.get("classes"))
    assignments = _items(data.get("assignments"))
    lessons = _items(data.get("lessons"))
    subject_map, teacher_map, grade_map = _by_id(subjects), _by_id(teachers), _by_id(grades)
    class_map, assignment_map = _by_id(classes), _by_id(assignments)

    assignment_rows = []
    teacher_assigned: set[int] = set()
    class_assigned: set[int] = set()
    assigned_subjects: set[int] = set()
    teaching_period_counts: Counter[int] = Counter()
    required: dict[int, int] = {}

    for row in assignments:
        aid = _safe_int(row.get("id"))
        teacher_id = _safe_int(row.get("teacher_id"))
        class_id = _safe_int(row.get("class_id"))
        subject_id = _safe_int(row.get("subject_id"))
        target = _safe_int(row.get("periods_per_week")) or 0
        if teacher_id is not None and teacher_id in teacher_map:
            teacher_assigned.add(teacher_id)
        if class_id is not None and class_id in class_map:
            class_assigned.add(class_id)
        if subject_id is not None and subject_id in subject_map:
            assigned_subjects.add(subject_id)
        if teacher_id is not None:
            teaching_period_counts[teacher_id] += target
        if aid is not None:
            required[aid] = target
        assignment_rows.append({
            "lớp": _label(class_map.get(class_id), "name") if class_id is not None else _label(row, "class_name"),
            "môn": _label(subject_map.get(subject_id), "name") if subject_id is not None else _label(row, "subject_name"),
            "giáo viên": _label(teacher_map.get(teacher_id), "name") if teacher_id is not None else _label(row, "teacher_name"),
            "số tiết mỗi tuần": target,
            "cách xếp tiết": _mode(row.get("block_mode")),
        })

    lesson_rows: list[dict[str, Any]] = []
    counted_lessons: Counter[int] = Counter()
    teacher_slot: dict[tuple[int, int], list[str]] = defaultdict(list)
    class_slot: dict[tuple[int, int], list[str]] = defaultdict(list)
    max_two_groups: dict[tuple[int, int, int], set[int]] = defaultdict(set)
    warnings: list[str] = []
    for lesson in lessons:
        aid = _safe_int(lesson.get("assignment_id"))
        slot = _safe_int(lesson.get("slot"))
        assignment = assignment_map.get(aid)
        time_label = _slot_text(slot, days, sessions, periods)
        if assignment is None or slot is None or time_label is None:
            warnings.append("Có tiết học không thể đối chiếu chính xác với phân công hoặc thời điểm.")
            continue
        teacher_id = _safe_int(assignment.get("teacher_id"))
        class_id = _safe_int(assignment.get("class_id"))
        subject_id = _safe_int(assignment.get("subject_id"))
        classroom = _label(class_map.get(class_id), "name")
        teacher = _label(teacher_map.get(teacher_id), "name")
        subject = _label(subject_map.get(subject_id), "name")
        lesson_rows.append({"lớp": classroom, "môn": subject, "giáo viên": teacher, "thời điểm": time_label,
                            "cố định": "Có" if lesson.get("locked") else "Không"})
        counted_lessons[aid] += 1
        if teacher_id is not None:
            teacher_slot[(teacher_id, slot)].append(classroom)
        if class_id is not None:
            class_slot[(class_id, slot)].append(subject)
        if assignment.get("block_mode") == "max_two_consecutive" and class_id is not None and subject_id is not None:
            max_two_groups[(class_id, subject_id, slot // periods)].add(slot % periods)

    # Group periods by teaching assignment before sending to the provider.
    # This preserves every period but avoids repeating long class/teacher names
    # on each row, which helps large schools stay under the context-size cap.
    grouped_lessons: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for row in lesson_rows:
        key = (row["lớp"], row["môn"], row["giáo viên"])
        stamp = row["thời điểm"] + (" (tiết cố định)" if row["cố định"] == "Có" else "")
        grouped_lessons[key].append(stamp)
    compact_schedule = [
        {"lớp": classroom, "môn": subject, "giáo viên": teacher, "các tiết học": times}
        for (classroom, subject, teacher), times in grouped_lessons.items()
    ]

    # These checks use only records actually received; a 'no problems detected'
    # statement is scoped to each check, never to the entire timetable.
    for (teacher_id, slot), rows in teacher_slot.items():
        if len(rows) > 1:
            warnings.append(f"Giáo viên {_label(teacher_map.get(teacher_id))} có {len(rows)} tiết ở cùng { _slot_text(slot, days, sessions, periods)}: lớp {', '.join(rows)}.")
    for (class_id, slot), rows in class_slot.items():
        if len(rows) > 1:
            warnings.append(f"Lớp {_label(class_map.get(class_id))} có {len(rows)} tiết ở cùng {_slot_text(slot, days, sessions, periods)}: môn {', '.join(rows)}.")
    for (class_id, subject_id, session_number), positions in max_two_groups.items():
        if len(positions) > 2 or (len(positions) == 2 and max(positions) - min(positions) != 1):
            start = session_number * periods
            warnings.append(f"Lớp {_label(class_map.get(class_id))}, môn {_label(subject_map.get(subject_id))}: cách phân bố tiết tại {_slot_text(start, days, sessions, periods)} cần kiểm tra theo chế độ tối đa hai tiết mỗi buổi.")

    missing = []
    for aid, target in required.items():
        actual = counted_lessons.get(aid, 0)
        if actual != target:
            assignment = assignment_map.get(aid)
            if not assignment:
                continue
            classroom = _label(class_map.get(_safe_int(assignment.get("class_id"))))
            subject = _label(subject_map.get(_safe_int(assignment.get("subject_id"))))
            missing.append(f"Lớp {classroom}, môn {subject}: đã xếp {actual} trên {target} tiết/tuần.")

    curriculum = []
    assigned_by_class_subject: Counter[tuple[int, int]] = Counter()
    for item in assignments:
        class_id = _safe_int(item.get("class_id"))
        subject_id = _safe_int(item.get("subject_id"))
        if class_id is not None and subject_id is not None:
            assigned_by_class_subject[(class_id, subject_id)] += _safe_int(item.get("periods_per_week")) or 0
    curriculum_mismatches = []
    for row in _items(data.get("grade_requirements")):
        grade_id, subject_id = _safe_int(row.get("grade_id")), _safe_int(row.get("subject_id"))
        curriculum.append({
            "khối": _label(grade_map.get(grade_id)),
            "môn": _label(subject_map.get(subject_id)),
            "số tiết mỗi tuần": _safe_int(row.get("periods_per_week")) or 0,
            "cách xếp tiết": _mode(row.get("block_mode")),
        })
        target = _safe_int(row.get("periods_per_week"))
        if target is None or grade_id is None or subject_id is None:
            continue
        for classroom in classes:
            if _safe_int(classroom.get("grade_id")) != grade_id:
                continue
            class_id = _safe_int(classroom.get("id"))
            actual = assigned_by_class_subject.get((class_id, subject_id), 0)
            if actual != target:
                curriculum_mismatches.append(
                    f"Lớp {_label(classroom)}, môn {_label(subject_map.get(subject_id))}: "
                    f"đang phân công {actual} tiết/tuần, định mức theo khối là {target} tiết/tuần."
                )

    coverage = data.get("coverage")
    coverage = coverage if isinstance(coverage, dict) else None
    duplicates = _items(coverage.get("duplicate_assignments")) if coverage is not None else []
    duplicate_descriptions = [
        f"Lớp {_label(x, 'class_name')}, môn {_label(x, 'subject_name')}: {', '.join(str(v) for v in x.get('teacher_names', []) if v)}"
        for x in duplicates
    ]
    over_capacity = _items(coverage.get("over_capacity_classes")) if coverage is not None else []

    return {
        "bộ thời khóa biểu": _label(project),
        "trường": str(project.get("school_name") or "Chưa cung cấp"),
        "thời gian học": f"{days} ngày mỗi tuần, {sessions} buổi mỗi ngày, {periods} tiết mỗi buổi" if days and sessions and periods else "Chưa cung cấp đầy đủ",
        "quy tắc xếp tiết": [
            "Xếp tiết linh hoạt không có nghĩa là bỏ qua xung đột giáo viên, lớp hoặc các quy tắc chung.",
            "Chế độ tối đa hai tiết: một môn trong một lớp chỉ có nhiều nhất hai tiết trong một buổi; nếu có hai tiết thì chúng phải liền nhau. Quy tắc này không giới hạn số tiết dạy liên tục của giáo viên.",
        ],
        "danh sách lớp": [{"lớp": _label(row), "khối": _label(grade_map.get(_safe_int(row.get("grade_id"))))} for row in classes],
        "giáo viên": [
            {"tên": _label(row), "được phân công": "Có" if _safe_int(row.get("id")) in teacher_assigned else "Chưa",
             "tổng số tiết được phân công mỗi tuần": teaching_period_counts.get(_safe_int(row.get("id")), 0)}
            for row in teachers
        ],
        "môn học": [_label(row) for row in subjects],
        "định mức theo khối": curriculum if "grade_requirements" in data else "Chưa có dữ liệu định mức theo khối trong phiên xem này; không kết luận tất cả các lớp đã đủ tiết.",
        "phân công giảng dạy": assignment_rows,
        "tiết đã xếp": compact_schedule,
        "kết quả đối chiếu tự động": {
            "phạm vi": "Chỉ các phân công và tiết học hiện có trong dữ liệu được cung cấp, không phải chứng nhận toàn bộ thời khóa biểu hợp lệ.",
            "xung đột thời điểm đã phát hiện": list(dict.fromkeys(warnings)),
            "phân công có số tiết đã xếp khác số tiết yêu cầu": missing,
            "phân công chưa khớp định mức theo khối": curriculum_mismatches if "grade_requirements" in data else "Chưa có dữ liệu định mức theo khối.",
            "giáo viên chưa được phân công": [_label(row) for row in teachers if _safe_int(row.get("id")) not in teacher_assigned],
            "lớp chưa có phân công": [_label(row) for row in classes if _safe_int(row.get("id")) not in class_assigned],
            "môn chưa được phân công": [_label(row) for row in subjects if _safe_int(row.get("id")) not in assigned_subjects],
            "phân công trùng đã được hệ thống kiểm tra": duplicate_descriptions if coverage is not None else "Chưa có kết quả kiểm tra của hệ thống trong phiên xem này.",
            "cảnh báo thiếu khả năng chứa tiết của lớp": len(over_capacity) if coverage is not None else "Chưa có dữ liệu kiểm tra.",
        },
        "số lượng": {"lớp": len(classes), "giáo viên": len(teachers), "môn": len(subjects),
                      "phân công": len(assignments), "tiết đã xếp": len(lesson_rows)},
    }
