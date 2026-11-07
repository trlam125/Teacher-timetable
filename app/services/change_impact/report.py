from collections import Counter

from app.services.change_impact.state import fingerprint

LABELS = {"name": "Tên", "short_name": "Tên ngắn", "teacher_id": "Giáo viên",
          "grade_id": "Khối", "periods_per_week": "Số tiết/tuần", "block_mode": "Chế độ tiết",
          "unavailable_json": "Tiết tránh", "blocked_slots_json": "Khóa lịch", "department_id": "Tổ bộ môn"}
TABLE_LABELS = {"departments": "Tổ bộ môn", "subjects": "Môn học", "teachers": "Giáo viên",
                "grades": "Khối", "classes": "Lớp", "teacher_subjects": "Môn giáo viên dạy",
                "grade_subject_requirements": "Chương trình khối", "teacher_preferences": "Nguyện vọng"}


def build_report(before, after, request, reasons=None):
    reasons = reasons or {}
    old = {table: {row["id"]: row for row in rows} for table, rows in before["tables"].items()}
    new = {table: {row["id"]: row for row in rows} for table, rows in after["tables"].items()}
    lookup = {key: {**old[key], **new[key]} for key in old}

    def label(table, value):
        if value is None:
            return "Không chọn"
        return lookup[table].get(value, {}).get("name", str(value))

    def assignment_info(row):
        return {"id": row["id"], "class_name": label("classes", row["class_id"]),
                "subject_name": label("subjects", row["subject_id"]),
                "teacher_name": label("teachers", row["teacher_id"])}

    def config_labels(rows, tables):
        labels = []
        for row in rows:
            parts = []
            for table, field in (("grades", "grade_id"), ("teachers", "teacher_id"), ("subjects", "subject_id")):
                if field in row:
                    parts.append(tables[table].get(row[field], {}).get("name", "Đã xóa"))
            if "periods_per_week" in row:
                parts.append(f"{row['periods_per_week']} tiết/tuần")
                parts.append({"required_double": "Tiết đôi bắt buộc", "preferred_double": "Ưu tiên tiết đôi"}.get(row["block_mode"], "Tiết đơn"))
            labels.append(" · ".join(parts))
        return labels

    assignment_actions, changes, lesson_actions = [], [], []
    touched = set()
    for aid, row in new["assignments"].items():
        if any(old[table].get(row[field]) != new[table].get(row[field]) for table, field in (
            ("teachers", "teacher_id"), ("classes", "class_id"), ("subjects", "subject_id"),
        )):
            touched.add(aid)
    for aid in sorted(set(old["assignments"]) | set(new["assignments"])):
        previous, current = old["assignments"].get(aid), new["assignments"].get(aid)
        if previous == current:
            continue
        touched.add(aid)
        row = previous or current
        assignment_actions.append({**assignment_info(row), "action": "delete" if current is None else "update"})
        if previous and current:
            for field in ("teacher_id", "periods_per_week", "block_mode"):
                if previous[field] != current[field]:
                    table = "teachers" if field == "teacher_id" else None
                    changes.append({"object": f'{label("classes", row["class_id"])} · {label("subjects", row["subject_id"])}',
                                    "field": LABELS[field],
                                    "before": label(table, previous[field]) if table else previous[field],
                                    "after": label(table, current[field]) if table else current[field]})
    old_count = Counter(row["assignment_id"] for row in old["lessons"].values())
    # A reduction first consumes periods already missing from the timetable.
    # Only scheduled periods above the new demand can be counted as surplus.
    surplus_ids = set()
    removed_by_assignment = {}
    for lid, row in old["lessons"].items():
        if lid not in new["lessons"]:
            removed_by_assignment.setdefault(row["assignment_id"], []).append(row)
    for aid, removed in removed_by_assignment.items():
        previous = old["assignments"][aid]
        current = new["assignments"].get(aid)
        if current is None:
            continue
        surplus = min(max(0, previous["periods_per_week"] - current["periods_per_week"]),
                      max(0, old_count[aid] - current["periods_per_week"]))
        # Prefer rows explicitly removed as excess over rows removed for conflicts.
        removed.sort(key=lambda row: (not reasons.get(row["id"], "").startswith("Bỏ tiết dư"), row["id"]))
        surplus_ids.update(row["id"] for row in removed[:surplus])
    counts = Counter()
    block_sets = {key: set() for key in ("to_tray", "surplus", "deleted")}
    for lid, row in old["lessons"].items():
        if lid in new["lessons"]:
            continue
        aid = row["assignment_id"]
        touched.add(aid)
        if aid not in new["assignments"]:
            action = "deleted"
        elif lid in surplus_ids:
            action = "surplus"
        else:
            action = "to_tray"
        counts[action] += 1
        block_sets[action].add((aid, row["block_id"] or lid))
        lesson_actions.append({**assignment_info(old["assignments"][aid]), "assignment_id": aid,
                               "lesson_id": lid, "slot": row["slot"], "block_id": row["block_id"],
                               "action": action, "reason": reasons.get(lid) or {
                                   "deleted": "Xóa cùng phân công", "surplus": "Giảm nhu cầu số tiết",
                                   "to_tray": "Không phù hợp với dữ liệu hoặc ràng buộc mới",
                               }[action]})
    for table, title in TABLE_LABELS.items():
        # Ignore generated primary keys in link/config rows: compare their semantic values.
        if table in {"teacher_subjects", "grade_subject_requirements"}:
            strip = lambda rows: sorted(({k: v for k, v in row.items() if k != "id"} for row in rows), key=fingerprint)
            a, b = strip(before["tables"][table]), strip(after["tables"][table])
            if a != b:
                changes.append({"object": title, "field": "Cấu hình", "before": config_labels(a, old), "after": config_labels(b, new)})
        else:
            for eid in sorted(set(old[table]) | set(new[table])):
                a, b = old[table].get(eid), new[table].get(eid)
                if a == b:
                    continue
                if a is None or b is None:
                    changes.append({"object": f'{title}: {(a or b).get("name", eid)}', "field": "Trạng thái",
                                    "before": "Có" if a else "Chưa có", "after": "Có" if b else "Xóa"})
                else:
                    for field, title_field in LABELS.items():
                        if field in a and a[field] != b[field]:
                            av, bv = a[field], b[field]
                            if field == "grade_id":
                                av, bv = label("grades", av), label("grades", bv)
                            changes.append({"object": f'{title}: {a.get("name", eid)}', "field": title_field,
                                            "before": av, "after": bv})
    new_count = Counter(row["assignment_id"] for row in new["lessons"].values())
    tray_before = sum(max(0, row["periods_per_week"] - old_count[aid]) for aid, row in old["assignments"].items())
    tray_after = sum(max(0, row["periods_per_week"] - new_count[aid]) for aid, row in new["assignments"].items())
    kept = sum(1 for row in new["lessons"].values() if row["assignment_id"] in touched and row["id"] in old["lessons"])
    # User can choose alternative surplus blocks, including when the default choice removed all of them.
    candidates = []
    for aid, row in old["assignments"].items():
        current = new["assignments"].get(aid)
        if current and current["periods_per_week"] < old_count[aid]:
            groups = {}
            for lesson in old["lessons"].values():
                if lesson["assignment_id"] == aid:
                    groups.setdefault(lesson["block_id"] or str(lesson["id"]), []).append(lesson)
            for block_id, rows in groups.items():
                candidates.append({"assignment_id": aid, **assignment_info(row), "block_id": block_id,
                                   "lesson_ids": [r["id"] for r in rows], "slots": [r["slot"] for r in rows],
                                   "protected": any(r["locked"] for r in rows) or any(
                                       f["assignment_id"] == aid and any(f["slot"] <= r["slot"] < f["slot"] + f["group_size"] for r in rows)
                                       for f in old["fixed_lessons"].values()),
                                   "selected": any(r["id"] not in new["lessons"] for r in rows)})
    requires_edit_mode = bool(assignment_actions or lesson_actions or any(
        row["field"] not in {"Tên", "Tên ngắn"} for row in changes
    ))
    return {"can_apply": True, "changed": before != after, "requires_edit_mode": requires_edit_mode, "changes": changes,
            "assignments": assignment_actions, "lesson_actions": lesson_actions,
            "blockers": [], "warnings": [], "removal_candidates": candidates,
            "totals": {"assignments_updated": sum(row["action"] == "update" for row in assignment_actions),
                       "assignments_deleted": sum(row["action"] == "delete" for row in assignment_actions),
                       "kept": kept, **{key: counts[key] for key in block_sets},
                       "blocks": {key: len(value) for key, value in block_sets.items()},
                       "affected_blocks": len(set().union(*block_sets.values())),
                       "tray_before": tray_before, "tray_after": tray_after}}
