from __future__ import annotations

import re
from typing import Any
from .parsing import *

from .analysis_core import *


def analyze_standalone_schedule_file(
    *,
    filename: str,
    content: bytes,
    include_editable: bool = False,
) -> dict[str, Any]:
    file_format, tables = read_tables(filename, content)
    raw_lessons, parse_warnings, detection = parse_tables_standalone(tables)
    if not raw_lessons:
        raise ScheduleAuditParseError(
            "Khong tim thay tiet hoc nao co the doc duoc. File can co thong tin Thu/Tiet va lop, mon hoac giao vien tuong ung."
        )
    project = infer_standalone_project(tables, raw_lessons)

    issues: list[dict[str, Any]] = []
    normalized_rows: list[dict[str, Any]] = []
    for raw in raw_lessons:
        slot = _resolve_slot(raw.day_text, raw.session_text, raw.period_text, project)
        if slot is None:
            issues.append(
                _issue(
                    "invalid_slot",
                    "error",
                    "Khong xac dinh duoc tiet hoc",
                    f"Khong doi duoc '{raw.day_text} / {raw.session_text or '-'} / {raw.period_text}' thanh mot o hop le.",
                    source=raw.source,
                )
            )
            continue
        class_name = _standalone_class_token(
            raw.class_text
        ) or _standalone_clean_entity_heading(raw.class_text)
        subject_name = _cell_text(raw.subject_text) or _standalone_subject_from_text(
            raw.lesson_text
        )
        teacher_name = _cell_text(raw.teacher_text)
        if not class_name:
            issues.append(
                _issue(
                    "unknown_class",
                    "error",
                    "Khong nhan dien duoc lop",
                    f"Khong tim thay ten lop trong o '{raw.lesson_text or raw.class_text}'.",
                    slot=slot,
                    project=project,
                    source=raw.source,
                )
            )
            continue
        if not subject_name:
            _class, subject_name, inferred_teacher = _standalone_parse_cell(
                raw.lesson_text,
                fixed_class=class_name,
                fixed_teacher=teacher_name,
            )
            teacher_name = teacher_name or inferred_teacher
        if not subject_name:
            subject_name = f"Mon chua xac dinh - {class_name}"
            issues.append(
                _issue(
                    "unknown_subject",
                    "warning",
                    "Chua xac dinh duoc mon hoc",
                    f"{class_name} tai {slot_label(slot, project)} khong co ten mon ro rang; he thong tao mon tam de van hien thi day du tiet tren bang.",
                    slot=slot,
                    project=project,
                    source=raw.source,
                    entity=class_name,
                )
            )
        if not teacher_name:
            teacher_name = f"GV chua xac dinh - {class_name} - {subject_name}"
            if not _standalone_teacher_is_optional(subject_name):
                issues.append(
                    _issue(
                        "unknown_teacher",
                        "warning",
                        "Chua xac dinh duoc giao vien",
                        f"{class_name} · {subject_name} khong co ten giao vien ro rang; he thong tao giao vien tam de khong lam mat tiet khi hien thi.",
                        slot=slot,
                        project=project,
                        source=raw.source,
                        entity=class_name,
                    )
                )
        normalized_rows.append(
            {
                "slot": slot,
                "class_name": class_name,
                "subject_name": subject_name,
                "teacher_name": teacher_name,
                "room": raw.room_text.strip(),
                "source": raw.source,
                "origin": raw.origin,
                "raw_text": _cell_text(raw.lesson_text)
                or " · ".join(part for part in (subject_name, teacher_name) if part),
            }
        )

    # Gop ban ghi trung hoan toan truoc khi tinh xung dot/thong ke. Mot dong bi
    # lap trong cung sheet khong phai la hai tiet hoc. Van giu co che gop cung mot
    # tiet neu no xuat hien o hai goc nhin lop/giao vien.
    deduplicated: list[dict[str, Any]] = []
    first_by_exact_key: dict[tuple[int, str, str, str, str], dict[str, Any]] = {}
    first_by_core_key: dict[tuple[int, str, str, str], dict[str, Any]] = {}

    def merge_source(target: dict[str, Any], incoming: dict[str, Any]) -> None:
        if incoming["source"] and incoming["source"] not in target["source"]:
            target["source"] += f"; {incoming['source']}"
        if not target["room"] and incoming["room"]:
            target["room"] = incoming["room"]

    for entry in normalized_rows:
        core_key = (
            int(entry["slot"]),
            _identity_text(entry["class_name"]),
            _identity_text(entry["subject_name"]),
            _identity_text(entry["teacher_name"]),
        )
        exact_key = (*core_key, _identity_text(entry["room"]))
        exact_existing = first_by_exact_key.get(exact_key)
        if exact_existing is not None:
            merge_source(exact_existing, entry)
            continue

        core_existing = first_by_core_key.get(core_key)
        rooms_compatible = bool(
            core_existing is not None
            and (
                not _identity_text(core_existing["room"])
                or not _identity_text(entry["room"])
                or _identity_text(core_existing["room"])
                == _identity_text(entry["room"])
            )
        )
        if (
            core_existing is not None
            and entry["origin"] != core_existing["origin"]
            and rooms_compatible
        ):
            merge_source(core_existing, entry)
            first_by_exact_key[(*core_key, _identity_text(core_existing["room"]))] = (
                core_existing
            )
            continue

        deduplicated.append(entry)
        first_by_exact_key[exact_key] = entry
        first_by_core_key.setdefault(core_key, entry)
    normalized_rows = deduplicated

    def unique_entity_names(field: str) -> list[str]:
        by_identity: dict[str, str] = {}
        for row in normalized_rows:
            name = row[field]
            by_identity.setdefault(_identity_text(name), name)
        return sorted(
            by_identity.values(),
            key=lambda value: (normalize_text(value), _identity_text(value)),
        )

    class_names = unique_entity_names("class_name")
    subject_names = unique_entity_names("subject_name")
    teacher_names = unique_entity_names("teacher_name")
    known_subject_names = [
        name for name in subject_names if not _standalone_is_unknown_subject(name)
    ]
    known_teacher_names = [
        name for name in teacher_names if not _standalone_is_unknown_teacher(name)
    ]
    class_ids = {
        _identity_text(name): index for index, name in enumerate(class_names, start=1)
    }
    subject_ids = {
        _identity_text(name): index for index, name in enumerate(subject_names, start=1)
    }
    teacher_ids = {
        _identity_text(name): index for index, name in enumerate(teacher_names, start=1)
    }

    classes = [
        {"id": item_id, "name": name, "grade_id": None, "unavailable": []}
        for name, item_id in (
            (name, class_ids[_identity_text(name)]) for name in class_names
        )
    ]
    subjects = [
        {
            "id": subject_ids[_identity_text(name)],
            "name": name,
            "short_name": _standalone_short_name(
                name, f"M{subject_ids[_identity_text(name)]}"
            ),
            "max_consecutive": int(project["periods"]),
            "is_placeholder": _standalone_is_unknown_subject(name),
        }
        for name in subject_names
    ]
    teachers = [
        {
            "id": teacher_ids[_identity_text(name)],
            "name": name,
            "short_name": _standalone_short_name(
                name, f"GV{teacher_ids[_identity_text(name)]}"
            ),
            "department_id": None,
            "max_periods_day": int(project["sessions"]) * int(project["periods"]),
            "unavailable": [],
            "subject_ids": [],
            "is_placeholder": _standalone_is_unknown_teacher(name),
        }
        for name in teacher_names
    ]

    assignment_keys: list[tuple[int, int, int]] = []
    assignment_counts: dict[tuple[int, int, int], int] = defaultdict(int)
    for row in normalized_rows:
        key = (
            class_ids[_identity_text(row["class_name"])],
            subject_ids[_identity_text(row["subject_name"])],
            teacher_ids[_identity_text(row["teacher_name"])],
        )
        if key not in assignment_counts:
            assignment_keys.append(key)
        assignment_counts[key] += 1
    assignments: list[dict[str, Any]] = []
    assignment_id_by_key: dict[tuple[int, int, int], int] = {}
    class_by_id = {row["id"]: row for row in classes}
    subject_by_id = {row["id"]: row for row in subjects}
    teacher_by_id = {row["id"]: row for row in teachers}
    for assignment_id, key in enumerate(assignment_keys, start=1):
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
        teacher_by_id[teacher_id]["subject_ids"].append(subject_id)

    recognized: list[dict[str, Any]] = []
    for index, row in enumerate(normalized_rows, start=1):
        key = (
            class_ids[_identity_text(row["class_name"])],
            subject_ids[_identity_text(row["subject_name"])],
            teacher_ids[_identity_text(row["teacher_name"])],
        )
        recognized.append(
            {
                "draft_id": index,
                "assignment_id": assignment_id_by_key[key],
                "slot": int(row["slot"]),
                "room": row["room"],
                "source": row["source"],
                "raw_text": row.get("raw_text", ""),
                "class_id": key[0],
                "subject_id": key[1],
                "teacher_id": key[2],
            }
        )

    conflict_codes_by_draft: dict[int, set[str]] = defaultdict(set)
    conflict_details_by_draft: dict[int, list[str]] = defaultdict(list)
    by_class_slot: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    by_teacher_slot: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    by_room_slot: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for entry in recognized:
        by_class_slot[(entry["slot"], entry["class_id"])].append(entry)
        # A placeholder only means the file did not provide a teacher. It must
        # never create a teacher-collision error because no real identity is known.
        if not teacher_by_id[int(entry["teacher_id"])].get("is_placeholder"):
            by_teacher_slot[(entry["slot"], entry["teacher_id"])].append(entry)
        room_key = normalize_text(entry["room"])
        if room_key:
            by_room_slot[(entry["slot"], room_key)].append(entry)
    for (slot, class_id), rows in by_class_slot.items():
        if len(rows) > 1:
            detail = (
                f"Lớp {class_by_id[class_id]['name']} có {len(rows)} tiết cùng lúc."
            )
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
                    source="; ".join(row["source"] for row in rows),
                    entity=class_by_id[class_id]["name"],
                )
            )
    for (slot, teacher_id), rows in by_teacher_slot.items():
        if len(rows) > 1:
            class_list = ", ".join(class_by_id[row["class_id"]]["name"] for row in rows)
            detail = f"Giáo viên {teacher_by_id[teacher_id]['name']} bị xếp đồng thời: {class_list}."
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
                    source="; ".join(row["source"] for row in rows),
                    entity=teacher_by_id[teacher_id]["name"],
                )
            )
    for (slot, _room), rows in by_room_slot.items():
        distinct_class_ids = {int(row["class_id"]) for row in rows}
        if len(distinct_class_ids) > 1:
            room = rows[0]["room"]
            class_names = sorted(
                {class_by_id[class_id]["name"] for class_id in distinct_class_ids},
                key=normalize_text,
            )
            detail = (
                f"Phòng {room} đang được dùng đồng thời cho: {', '.join(class_names)}."
            )
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
                    source="; ".join(row["source"] for row in rows),
                    entity=room,
                )
            )
    for warning in parse_warnings:
        issues.append(
            _issue("unread_table", "warning", "Co bang/sheet chua doc duoc", warning)
        )

    # Neu mot dong du lieu bi lap, cac canh bao phat sinh truoc buoc gop tiet cung
    # khong nen xuat hien lap lai. Gop issue trung noi dung va noi nguon de nguoi
    # dung van truy vet duoc vi tri trong file.
    deduplicated_issues: list[dict[str, Any]] = []
    first_issue_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for issue in issues:
        issue_key = (
            issue.get("code"),
            issue.get("severity"),
            issue.get("title"),
            issue.get("detail"),
            issue.get("slot"),
            issue.get("entity"),
        )
        existing_issue = first_issue_by_key.get(issue_key)
        if existing_issue is not None:
            source = _cell_text(issue.get("source"))
            if source and source not in existing_issue.get("source", ""):
                existing_issue["source"] = (
                    f"{existing_issue.get('source', '')}; {source}".strip("; ")
                )
            continue
        first_issue_by_key[issue_key] = issue
        deduplicated_issues.append(issue)
    issues = deduplicated_issues

    severity_order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(
        key=lambda item: (
            severity_order.get(item["severity"], 9),
            item.get("slot") is None,
            item.get("slot") or -1,
            item["title"],
        )
    )
    errors = sum(1 for item in issues if item["severity"] == "error")
    warnings = sum(1 for item in issues if item["severity"] == "warning")
    collisions = sum(
        1
        for item in issues
        if item["code"] in {"teacher_collision", "class_collision", "room_collision"}
    )
    detection.update(
        {
            "scope_label": f"Doc lap · {len(classes)} lop · {len(known_teacher_names)} giao vien · {len(known_subject_names)} mon",
            "classes": [row["name"] for row in classes],
            "teachers": known_teacher_names,
        }
    )

    viewer_cells: list[dict[str, Any]] = []
    affected_coordinates: set[tuple[int, int]] = set()
    for entry in recognized:
        class_id = int(entry["class_id"])
        subject_id = int(entry["subject_id"])
        teacher_id = int(entry["teacher_id"])
        codes = sorted(conflict_codes_by_draft.get(int(entry["draft_id"]), set()))
        if codes:
            affected_coordinates.add((int(entry["slot"]), class_id))
        viewer_cells.append(
            {
                "draft_id": int(entry["draft_id"]),
                "slot": int(entry["slot"]),
                "class_id": class_id,
                "class_name": class_by_id[class_id]["name"],
                "subject_name": subject_by_id[subject_id]["name"],
                "teacher_name": teacher_by_id[teacher_id]["name"],
                "room": entry.get("room", ""),
                "source": entry.get("source", ""),
                "raw_text": entry.get("raw_text", ""),
                "conflicts": codes,
                "conflict_details": conflict_details_by_draft.get(
                    int(entry["draft_id"]), []
                ),
            }
        )
    viewer = {
        "days": int(project["days"]),
        "sessions": int(project["sessions"]),
        "periods": int(project["periods"]),
        "classes": [{"id": row["id"], "name": row["name"]} for row in classes],
        "cells": viewer_cells,
        "conflict_cells": len(affected_coordinates),
    }
    statistics = _standalone_statistics(
        recognized,
        class_by_id=class_by_id,
        subject_by_id=subject_by_id,
        teacher_by_id=teacher_by_id,
    )
    result = {
        "ok": True,
        "filename": filename,
        "format": file_format,
        "detection": detection,
        "status": "clean"
        if errors == 0 and warnings == 0
        else ("error" if errors else "warning"),
        "summary": {
            "read_lessons": len(raw_lessons),
            "recognized_lessons": len(recognized),
            "errors": errors,
            "warnings": warnings,
            "collisions": collisions,
            "missing_periods": 0,
            "extra_periods": 0,
            "classes": len(classes),
            "teachers": len(known_teacher_names),
            "subjects": len(known_subject_names),
        },
        "issues": issues,
        "viewer": viewer,
        "statistics": statistics,
        "data": {
            "project": project,
            "classes": classes,
            "subjects": subjects,
            "teachers": teachers,
            "assignments": assignments,
            "lessons": [],
        },
    }
    if include_editable:
        result["editable_lessons"] = [
            {
                "draft_id": row["draft_id"],
                "assignment_id": row["assignment_id"],
                "slot": row["slot"],
            }
            for row in recognized
        ]
    return result


__all__ = [name for name in globals() if not name.startswith("__")]
