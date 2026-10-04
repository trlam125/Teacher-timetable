from __future__ import annotations

from typing import Any
from .parsing import *

from .analysis_core import *


def recalculate_standalone_edited_report(report: dict[str, Any]) -> dict[str, Any]:
    """Rebuild all rule-derived standalone audit data from edited viewer cells.

    The browser is allowed to edit teacher/subject text, but conflicts, issues,
    statistics, summaries and normalized entities are server-owned derived data.
    Recomputing them here prevents stale or tampered client-side calculations
    from being sent to the AI as if they were authoritative.
    """
    if not isinstance(report, dict) or report.get("ok") is not True:
        raise ValueError("invalid report")
    viewer = report.get("viewer")
    if not isinstance(viewer, dict):
        raise ValueError("missing viewer")

    try:
        days = int(viewer.get("days") or 0)
        sessions = int(viewer.get("sessions") or 0)
        periods = int(viewer.get("periods") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid schedule dimensions") from exc
    if not (1 <= days <= 7 and 1 <= sessions <= 4 and 1 <= periods <= 20):
        raise ValueError("invalid schedule dimensions")
    total_slots = days * sessions * periods
    project = {
        "days": days,
        "sessions": sessions,
        "periods": periods,
    }
    existing_project = (
        (report.get("data") or {}).get("project")
        if isinstance(report.get("data"), dict)
        else None
    )
    if isinstance(existing_project, dict):
        project = {**existing_project, **project}

    raw_classes = viewer.get("classes")
    if not isinstance(raw_classes, list) or not raw_classes or len(raw_classes) > 5000:
        raise ValueError("invalid classes")
    classes: list[dict[str, Any]] = []
    class_by_id: dict[int, dict[str, Any]] = {}
    for item in raw_classes:
        if not isinstance(item, dict):
            raise ValueError("invalid class")
        try:
            class_id = int(item.get("id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid class id") from exc
        name = _cell_text(item.get("name"))[:160]
        if class_id <= 0 or class_id in class_by_id or not name:
            raise ValueError("invalid class")
        row = {"id": class_id, "name": name}
        classes.append(row)
        class_by_id[class_id] = row

    raw_cells = viewer.get("cells")
    if not isinstance(raw_cells, list) or len(raw_cells) > 50000:
        raise ValueError("invalid cells")

    normalized_rows: list[dict[str, Any]] = []
    seen_draft_ids: set[int] = set()
    for index, item in enumerate(raw_cells, start=1):
        if not isinstance(item, dict):
            raise ValueError("invalid cell")
        try:
            draft_id = int(item.get("draft_id") or index)
            slot = int(item.get("slot"))
            class_id = int(item.get("class_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid cell coordinates") from exc
        if draft_id <= 0 or draft_id in seen_draft_ids:
            raise ValueError("invalid draft id")
        if not (0 <= slot < total_slots) or class_id not in class_by_id:
            raise ValueError("cell outside schedule")
        seen_draft_ids.add(draft_id)
        class_name = class_by_id[class_id]["name"]
        subject_name = _cell_text(item.get("subject_name"))[:200]
        teacher_name = _cell_text(item.get("teacher_name"))[:200]
        if not subject_name:
            subject_name = f"Mon chua xac dinh - {class_name}"
        if not teacher_name:
            teacher_name = f"GV chua xac dinh - {class_name} - {subject_name}"
        normalized_rows.append(
            {
                "draft_id": draft_id,
                "slot": slot,
                "class_id": class_id,
                "class_name": class_name,
                "subject_name": subject_name,
                "teacher_name": teacher_name,
                "room": _cell_text(item.get("room"))[:120],
                "source": _cell_text(item.get("source"))[:500],
                "raw_text": _cell_text(item.get("raw_text"))[:500],
            }
        )

    data = report.get("data") if isinstance(report.get("data"), dict) else {}
    previous_subjects = (
        data.get("subjects") if isinstance(data.get("subjects"), list) else []
    )
    previous_teachers = (
        data.get("teachers") if isinstance(data.get("teachers"), list) else []
    )
    previous_subject_by_key = {
        _identity_text(row.get("name")): row
        for row in previous_subjects
        if isinstance(row, dict) and _identity_text(row.get("name"))
    }
    previous_teacher_by_key = {
        _identity_text(row.get("name")): row
        for row in previous_teachers
        if isinstance(row, dict) and _identity_text(row.get("name"))
    }
    used_subject_ids: set[int] = set()
    used_teacher_ids: set[int] = set()
    max_subject_id = max(
        (
            int(row.get("id") or 0)
            for row in previous_subjects
            if isinstance(row, dict) and str(row.get("id") or "").isdigit()
        ),
        default=0,
    )
    max_teacher_id = max(
        (
            int(row.get("id") or 0)
            for row in previous_teachers
            if isinstance(row, dict) and str(row.get("id") or "").isdigit()
        ),
        default=0,
    )
    next_subject_id = max_subject_id + 1
    next_teacher_id = max_teacher_id + 1
    subjects_by_key: dict[str, dict[str, Any]] = {}
    teachers_by_key: dict[str, dict[str, Any]] = {}

    def allocate_id(previous: Any, used: set[int], next_value: int) -> tuple[int, int]:
        try:
            preferred = int(previous)
        except (TypeError, ValueError):
            preferred = 0
        if preferred > 0 and preferred not in used:
            used.add(preferred)
            return preferred, next_value
        while next_value in used:
            next_value += 1
        result = next_value
        used.add(result)
        return result, result + 1

    def subject_for(name: str) -> dict[str, Any]:
        nonlocal next_subject_id
        key = _identity_text(name)
        existing = subjects_by_key.get(key)
        if existing is not None:
            return existing
        previous = previous_subject_by_key.get(key, {})
        subject_id, next_subject_id = allocate_id(
            previous.get("id"), used_subject_ids, next_subject_id
        )
        row = {
            "id": subject_id,
            "name": name,
            "short_name": _cell_text(previous.get("short_name"))[:20]
            or _standalone_short_name(name, f"M{subject_id}"),
            "is_placeholder": _standalone_is_unknown_subject(name),
        }
        subjects_by_key[key] = row
        return row

    def teacher_for(name: str) -> dict[str, Any]:
        nonlocal next_teacher_id
        key = _identity_text(name)
        existing = teachers_by_key.get(key)
        if existing is not None:
            return existing
        previous = previous_teacher_by_key.get(key, {})
        teacher_id, next_teacher_id = allocate_id(
            previous.get("id"), used_teacher_ids, next_teacher_id
        )
        row = {
            "id": teacher_id,
            "name": name,
            "short_name": _cell_text(previous.get("short_name"))[:20]
            or _standalone_short_name(name, f"GV{teacher_id}"),
            "is_placeholder": _standalone_is_unknown_teacher(name),
            "subject_ids": [],
        }
        teachers_by_key[key] = row
        return row

    assignment_counts: dict[tuple[int, int, int], int] = defaultdict(int)
    assignment_order: list[tuple[int, int, int]] = []
    recognized: list[dict[str, Any]] = []
    entity_ids_by_draft: dict[int, tuple[int, int]] = {}
    for row in normalized_rows:
        subject = subject_for(row["subject_name"])
        teacher = teacher_for(row["teacher_name"])
        subject_id = int(subject["id"])
        teacher_id = int(teacher["id"])
        if subject_id not in teacher["subject_ids"]:
            teacher["subject_ids"].append(subject_id)
        key = (int(row["class_id"]), subject_id, teacher_id)
        if key not in assignment_counts:
            assignment_order.append(key)
        assignment_counts[key] += 1
        entity_ids_by_draft[int(row["draft_id"])] = (subject_id, teacher_id)

    subjects = list(subjects_by_key.values())
    teachers = list(teachers_by_key.values())
    subject_by_id = {int(row["id"]): row for row in subjects}
    teacher_by_id = {int(row["id"]): row for row in teachers}
    assignments: list[dict[str, Any]] = []
    assignment_id_by_key: dict[tuple[int, int, int], int] = {}
    for assignment_id, key in enumerate(assignment_order, start=1):
        class_id, subject_id, teacher_id = key
        assignment_id_by_key[key] = assignment_id
        assignments.append(
            {
                "id": assignment_id,
                "class_id": class_id,
                "subject_id": subject_id,
                "teacher_id": teacher_id,
                "periods_per_week": assignment_counts[key],
                "block_mode": "free",
                "class_name": class_by_id[class_id]["name"],
                "subject_name": subject_by_id[subject_id]["name"],
                "subject_short": subject_by_id[subject_id]["short_name"],
                "teacher_name": teacher_by_id[teacher_id]["name"],
                "teacher_short": teacher_by_id[teacher_id]["short_name"],
            }
        )

    issues = [
        dict(issue)
        for issue in (report.get("issues") or [])
        if isinstance(issue, dict)
        and issue.get("code")
        not in {
            "teacher_collision",
            "class_collision",
            "room_collision",
            "unknown_subject",
            "unknown_teacher",
        }
    ]
    for row in normalized_rows:
        subject_id, teacher_id = entity_ids_by_draft[int(row["draft_id"])]
        key = (int(row["class_id"]), subject_id, teacher_id)
        recognized.append(
            {
                "draft_id": int(row["draft_id"]),
                "assignment_id": assignment_id_by_key[key],
                "slot": int(row["slot"]),
                "room": row["room"],
                "source": row["source"],
                "raw_text": row["raw_text"],
                "class_id": int(row["class_id"]),
                "subject_id": subject_id,
                "teacher_id": teacher_id,
            }
        )
        if _standalone_is_unknown_subject(row["subject_name"]):
            issues.append(
                _issue(
                    "unknown_subject",
                    "warning",
                    "Chua xac dinh duoc mon hoc",
                    f"{row['class_name']} tai {slot_label(int(row['slot']), project)} chua co ten mon ro rang.",
                    slot=int(row["slot"]),
                    project=project,
                    source=row["source"],
                    entity=row["class_name"],
                )
            )
        if _standalone_is_unknown_teacher(
            row["teacher_name"]
        ) and not _standalone_teacher_is_optional(row["subject_name"]):
            issues.append(
                _issue(
                    "unknown_teacher",
                    "warning",
                    "Chua xac dinh duoc giao vien",
                    f"{row['class_name']} · {row['subject_name']} chua co ten giao vien ro rang.",
                    slot=int(row["slot"]),
                    project=project,
                    source=row["source"],
                    entity=row["class_name"],
                )
            )

    conflict_codes_by_draft: dict[int, set[str]] = defaultdict(set)
    conflict_details_by_draft: dict[int, list[str]] = defaultdict(list)
    by_class_slot: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    by_teacher_slot: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    by_room_slot: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for entry in recognized:
        slot = int(entry["slot"])
        class_id = int(entry["class_id"])
        teacher_id = int(entry["teacher_id"])
        by_class_slot[(slot, class_id)].append(entry)
        if not teacher_by_id[teacher_id].get("is_placeholder"):
            by_teacher_slot[(slot, teacher_id)].append(entry)
        room_key = normalize_text(entry["room"])
        if room_key:
            by_room_slot[(slot, room_key)].append(entry)

    for (slot, class_id), rows in by_class_slot.items():
        if len(rows) <= 1:
            continue
        detail = f"Lớp {class_by_id[class_id]['name']} có {len(rows)} tiết cùng lúc."
        for row in rows:
            conflict_codes_by_draft[int(row["draft_id"])].add("class_collision")
            conflict_details_by_draft[int(row["draft_id"])].append(detail)
        issues.append(
            _issue(
                "class_collision",
                "error",
                "Trung lich lop",
                detail,
                slot=slot,
                project=project,
                source="; ".join(row["source"] for row in rows if row["source"]),
                entity=class_by_id[class_id]["name"],
            )
        )
    for (slot, teacher_id), rows in by_teacher_slot.items():
        if len(rows) <= 1:
            continue
        class_names = list(
            dict.fromkeys(class_by_id[int(row["class_id"])]["name"] for row in rows)
        )
        detail = f"Giáo viên {teacher_by_id[teacher_id]['name']} bị xếp đồng thời: {', '.join(class_names)}."
        for row in rows:
            conflict_codes_by_draft[int(row["draft_id"])].add("teacher_collision")
            conflict_details_by_draft[int(row["draft_id"])].append(detail)
        issues.append(
            _issue(
                "teacher_collision",
                "error",
                "Trung lich giao vien",
                detail,
                slot=slot,
                project=project,
                source="; ".join(row["source"] for row in rows if row["source"]),
                entity=teacher_by_id[teacher_id]["name"],
            )
        )
    for (slot, _room_key), rows in by_room_slot.items():
        distinct_class_ids = {int(row["class_id"]) for row in rows}
        if len(distinct_class_ids) <= 1:
            continue
        room = rows[0]["room"]
        class_names = sorted(
            {class_by_id[class_id]["name"] for class_id in distinct_class_ids},
            key=normalize_text,
        )
        detail = f"Phòng {room} đang được dùng đồng thời cho: {', '.join(class_names)}."
        for row in rows:
            conflict_codes_by_draft[int(row["draft_id"])].add("room_collision")
            conflict_details_by_draft[int(row["draft_id"])].append(detail)
        issues.append(
            _issue(
                "room_collision",
                "error",
                "Trung phong hoc",
                detail,
                slot=slot,
                project=project,
                source="; ".join(row["source"] for row in rows if row["source"]),
                entity=room,
            )
        )

    severity_order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(
        key=lambda item: (
            severity_order.get(str(item.get("severity")), 9),
            item.get("slot") is None,
            int(item.get("slot") or -1),
            str(item.get("title") or ""),
        )
    )
    errors = sum(1 for item in issues if item.get("severity") == "error")
    warnings = sum(1 for item in issues if item.get("severity") == "warning")
    collision_count = sum(
        1
        for item in issues
        if item.get("code")
        in {"teacher_collision", "class_collision", "room_collision"}
    )

    affected_coordinates: set[tuple[int, int]] = set()
    cells: list[dict[str, Any]] = []
    row_by_draft = {int(row["draft_id"]): row for row in normalized_rows}
    for entry in recognized:
        draft_id = int(entry["draft_id"])
        row = row_by_draft[draft_id]
        codes = sorted(conflict_codes_by_draft.get(draft_id, set()))
        if codes:
            affected_coordinates.add((int(entry["slot"]), int(entry["class_id"])))
        cells.append(
            {
                "draft_id": draft_id,
                "slot": int(entry["slot"]),
                "class_id": int(entry["class_id"]),
                "class_name": row["class_name"],
                "subject_name": row["subject_name"],
                "teacher_name": row["teacher_name"],
                "room": row["room"],
                "source": row["source"],
                "raw_text": row["raw_text"],
                "conflicts": codes,
                "conflict_details": conflict_details_by_draft.get(draft_id, []),
            }
        )

    statistics = _standalone_statistics(
        recognized,
        class_by_id=class_by_id,
        subject_by_id=subject_by_id,
        teacher_by_id=teacher_by_id,
    )
    known_teachers = [row["name"] for row in teachers if not row.get("is_placeholder")]
    known_subjects = [row["name"] for row in subjects if not row.get("is_placeholder")]
    viewer.update(
        {
            "days": days,
            "sessions": sessions,
            "periods": periods,
            "classes": classes,
            "cells": cells,
            "conflict_cells": len(affected_coordinates),
        }
    )
    report["viewer"] = viewer
    report["issues"] = issues
    report["statistics"] = statistics
    report["status"] = "error" if errors else ("warning" if warnings else "clean")
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    summary.update(
        {
            "recognized_lessons": len(recognized),
            "errors": errors,
            "warnings": warnings,
            "collisions": collision_count,
            "classes": len(classes),
            "teachers": len(known_teachers),
            "subjects": len(known_subjects),
        }
    )
    report["summary"] = summary
    detection = (
        report.get("detection") if isinstance(report.get("detection"), dict) else {}
    )
    detection["classes"] = [row["name"] for row in classes]
    detection["teachers"] = known_teachers
    detection["scope_label"] = (
        f"Doc lap · {len(classes)} lop · {len(known_teachers)} giao vien · {len(known_subjects)} mon"
    )
    report["detection"] = detection
    report["data"] = {
        **data,
        "project": project,
        "classes": classes,
        "subjects": subjects,
        "teachers": teachers,
        "assignments": assignments,
        "lessons": [
            {
                "id": int(entry["draft_id"]),
                "assignment_id": int(entry["assignment_id"]),
                "slot": int(entry["slot"]),
                "locked": False,
            }
            for entry in recognized
        ],
    }
    return report


def apply_standalone_viewer_edits(
    base_report: dict[str, Any],
    edited_report: dict[str, Any],
) -> dict[str, Any]:
    """Apply only the explicitly editable fields onto a freshly parsed report."""
    base_viewer = base_report.get("viewer") if isinstance(base_report, dict) else None
    edited_viewer = (
        edited_report.get("viewer") if isinstance(edited_report, dict) else None
    )
    if not isinstance(base_viewer, dict) or not isinstance(edited_viewer, dict):
        raise ValueError("missing viewer")
    base_cells = base_viewer.get("cells")
    edited_cells = edited_viewer.get("cells")
    if not isinstance(base_cells, list) or not isinstance(edited_cells, list):
        raise ValueError("missing cells")

    edited_by_draft: dict[int, dict[str, Any]] = {}
    for index, cell in enumerate(edited_cells, start=1):
        if not isinstance(cell, dict):
            raise ValueError("invalid edited cell")
        try:
            draft_id = int(cell.get("draft_id") or index)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid edited draft id") from exc
        if draft_id <= 0 or draft_id in edited_by_draft:
            raise ValueError("duplicate edited draft id")
        edited_by_draft[draft_id] = cell

    base_draft_ids: set[int] = set()
    for index, cell in enumerate(base_cells, start=1):
        if not isinstance(cell, dict):
            raise ValueError("invalid base cell")
        try:
            draft_id = int(cell.get("draft_id") or index)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid base draft id") from exc
        base_draft_ids.add(draft_id)
        edited = edited_by_draft.get(draft_id)
        if edited is None:
            raise ValueError("edited timetable does not match source file")
        subject_name = _cell_text(edited.get("subject_name"))[:200]
        teacher_name = _cell_text(edited.get("teacher_name"))[:200]
        if not subject_name or not teacher_name:
            raise ValueError("empty edited entity")
        cell["subject_name"] = subject_name
        cell["teacher_name"] = teacher_name
        cell["raw_text"] = " - ".join(
            part for part in (subject_name, teacher_name) if part
        )

    if set(edited_by_draft) != base_draft_ids:
        raise ValueError("edited timetable does not match source file")
    return recalculate_standalone_edited_report(base_report)


__all__ = [name for name in globals() if not name.startswith("__")]
