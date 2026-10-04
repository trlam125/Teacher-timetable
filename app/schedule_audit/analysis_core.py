from __future__ import annotations

import re
from typing import Any
from .parsing import *


def infer_standalone_project(
    tables: list[tuple[str, list[list[str]]]],
    raw_lessons: list[RawLesson],
) -> dict[str, Any]:
    day_indexes: set[int] = set()
    explicit_sessions: set[int] = set()
    period_numbers: list[int] = []
    for _title, raw_rows in tables:
        rows = _trim_matrix(raw_rows)
        grid = _standalone_find_grid_header(rows)
        if grid:
            header_index, day_cols, period_col, session_col = grid
            for _col, day_text in day_cols:
                day = _standalone_day_index(day_text)
                if day is not None:
                    day_indexes.add(day)
            for values in rows[header_index + 1 :]:
                if period_col < len(values):
                    number = _period_number(_cell_text(values[period_col]))
                    if number is not None:
                        period_numbers.append(number)
                if session_col is not None and session_col < len(values):
                    session = _session_index(_cell_text(values[session_col]), 2)
                    if session is not None:
                        explicit_sessions.add(session)
        else:
            for header_index, row in enumerate(rows[:30]):
                kinds = {
                    _header_kind(_cell_text(value)): col
                    for col, value in enumerate(row)
                    if _header_kind(_cell_text(value))
                }
                if "period" not in kinds or "day" not in kinds:
                    continue
                for values in rows[header_index + 1 :]:
                    if kinds["day"] < len(values):
                        day = _standalone_day_index(_cell_text(values[kinds["day"]]))
                        if day is not None:
                            day_indexes.add(day)
                    if kinds["period"] < len(values):
                        number = _period_number(_cell_text(values[kinds["period"]]))
                        if number is not None:
                            period_numbers.append(number)
                    if "session" in kinds and kinds["session"] < len(values):
                        session = _session_index(
                            _cell_text(values[kinds["session"]]), 2
                        )
                        if session is not None:
                            explicit_sessions.add(session)
                break
    for raw in raw_lessons:
        day = _standalone_day_index(raw.day_text)
        if day is not None:
            day_indexes.add(day)
        number = _period_number(raw.period_text)
        if number is not None:
            period_numbers.append(number)
        if raw.session_text:
            session = _session_index(raw.session_text, 2)
            if session is not None:
                explicit_sessions.add(session)
    days = max(day_indexes) + 1 if day_indexes else 6
    days = max(5, min(7, days))
    maximum_period = max(period_numbers, default=5)
    if 1 in explicit_sessions:
        sessions = 2
        periods = max(1, min(8, maximum_period))
    elif maximum_period > 8:
        sessions = 2
        periods = max(1, min(8, (maximum_period + 1) // 2))
    else:
        sessions = 1
        periods = max(1, min(8, maximum_period))
    return {
        "id": 0,
        "name": "TKB import",
        "school_name": "Truong hoc",
        "days": days,
        "sessions": sessions,
        "periods": periods,
        "blocked_slots": [],
    }


def _standalone_short_name(value: str, fallback: str) -> str:
    words = [word for word in re.split(r"\s+", _cell_text(value)) if word]
    if not words:
        return fallback[:20]
    if len(words) == 1:
        return words[0][:20].upper()
    return "".join(word[0] for word in words if word)[:20].upper() or fallback[:20]


def _standalone_is_unknown_subject(value: str) -> bool:
    return normalize_text(value).startswith("mon chua xac dinh")


def _standalone_is_unknown_teacher(value: str) -> bool:
    return normalize_text(value).startswith("gv chua xac dinh")


def _standalone_statistics(
    recognized: list[dict[str, Any]],
    *,
    class_by_id: dict[int, dict[str, Any]],
    subject_by_id: dict[int, dict[str, Any]],
    teacher_by_id: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Build timetable statistics without counting placeholder entities as real data."""
    teacher_rows: dict[int, dict[str, Any]] = {}
    subject_rows: dict[int, dict[str, Any]] = {}
    class_rows: dict[int, dict[str, Any]] = {}

    def bump(bucket: dict[str, int], name: str) -> None:
        bucket[name] = bucket.get(name, 0) + 1

    for entry in recognized:
        class_id = int(entry["class_id"])
        subject_id = int(entry["subject_id"])
        teacher_id = int(entry["teacher_id"])
        class_name = class_by_id[class_id]["name"]
        subject_name = subject_by_id[subject_id]["name"]
        teacher_name = teacher_by_id[teacher_id]["name"]
        known_subject = not _standalone_is_unknown_subject(subject_name)
        known_teacher = not _standalone_is_unknown_teacher(teacher_name)

        if known_teacher:
            teacher = teacher_rows.setdefault(
                teacher_id,
                {
                    "id": teacher_id,
                    "name": teacher_name,
                    "total_lessons": 0,
                    "subjects": {},
                    "classes": {},
                },
            )
            teacher["total_lessons"] += 1
            if known_subject:
                bump(teacher["subjects"], subject_name)
            bump(teacher["classes"], class_name)

        if known_subject:
            subject = subject_rows.setdefault(
                subject_id,
                {
                    "id": subject_id,
                    "name": subject_name,
                    "total_lessons": 0,
                    "teachers": {},
                    "classes": {},
                },
            )
            subject["total_lessons"] += 1
            if known_teacher:
                bump(subject["teachers"], teacher_name)
            bump(subject["classes"], class_name)

        class_row = class_rows.setdefault(
            class_id,
            {
                "id": class_id,
                "name": class_name,
                "total_lessons": 0,
                "subjects": {},
                "teachers": {},
            },
        )
        class_row["total_lessons"] += 1
        if known_subject:
            bump(class_row["subjects"], subject_name)
        if known_teacher:
            bump(class_row["teachers"], teacher_name)

    def breakdown(mapping: dict[str, int]) -> list[dict[str, Any]]:
        return [
            {"name": name, "lessons": count}
            for name, count in sorted(
                mapping.items(),
                key=lambda item: (
                    -item[1],
                    normalize_text(item[0]),
                    _identity_text(item[0]),
                ),
            )
        ]

    def finalize(
        rows: dict[int, dict[str, Any]], detail_fields: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row in rows.values():
            item = dict(row)
            for field in detail_fields:
                item[field] = breakdown(item[field])
            result.append(item)
        result.sort(
            key=lambda item: (
                -int(item["total_lessons"]),
                normalize_text(item["name"]),
                _identity_text(item["name"]),
            )
        )
        return result

    teachers = finalize(teacher_rows, ("subjects", "classes"))
    subjects = finalize(subject_rows, ("teachers", "classes"))
    classes = finalize(class_rows, ("subjects", "teachers"))

    def leader(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not rows:
            return None
        return {"name": rows[0]["name"], "lessons": int(rows[0]["total_lessons"])}

    total_lessons = len(recognized)
    known_teacher_lessons = sum(int(row["total_lessons"]) for row in teachers)
    return {
        "overview": {
            "total_lessons": total_lessons,
            "total_teachers": len(teachers),
            "total_subjects": len(subjects),
            "total_classes": len(classes),
            "avg_lessons_per_teacher": round(known_teacher_lessons / len(teachers), 2)
            if teachers
            else 0,
            "avg_lessons_per_class": round(total_lessons / len(classes), 2)
            if classes
            else 0,
            "busiest_teacher": leader(teachers),
            "largest_subject": leader(subjects),
            "busiest_class": leader(classes),
        },
        "teachers": teachers,
        "subjects": subjects,
        "classes": classes,
    }


__all__ = [name for name in globals() if not name.startswith("__")]
