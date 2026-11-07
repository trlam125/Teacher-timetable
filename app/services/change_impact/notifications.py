from app.services.change_impact.state import encoded
from app.services.notification_models import ScheduleNotification, ScheduleNotificationDetail
from app.services.schedule_notifications import MAX_DETAILS_PER_NOTICE


def record_change_notice(db, project, before, after, message, *, restored=False):
    """Record each net lesson change once, including Core-based restoration."""
    notices = db.info.setdefault("_schedule_notification_per_transaction", {})
    notice = notices.get(project.id)
    if notice is None:
        notice = ScheduleNotification(project_id=project.id)
        db.add(notice)
        notices[project.id] = notice
    notice.summary_text = message
    old_lessons = {row["id"]: row for row in before["tables"]["lessons"]}
    new_lessons = {row["id"]: row for row in after["tables"]["lessons"]}
    old_assignments = {row["id"]: row for row in before["tables"]["assignments"]}
    new_assignments = {row["id"]: row for row in after["tables"]["assignments"]}
    names = {
        side: {table: {item["id"]: item["name"] for item in state["tables"][table]}
               for table in ("classes", "subjects", "teachers")}
        for side, state in (("before", before), ("after", after))
    }

    def snapshot(side, row, assignments):
        if row is None:
            return None
        assignment = assignments.get(row["assignment_id"])
        if not assignment:
            return None
        return {"assignment_id": row["assignment_id"], "slot": row["slot"], "locked": row["locked"],
                "class_id": assignment["class_id"], "subject_id": assignment["subject_id"],
                "teacher_id": assignment["teacher_id"],
                "class_name": names[side]["classes"].get(assignment["class_id"], ""),
                "subject_name": names[side]["subjects"].get(assignment["subject_id"], ""),
                "teacher_name": names[side]["teachers"].get(assignment["teacher_id"], "")}

    counts = {"added": 0, "removed": 0, "moved": 0, "locked": 0}
    details = []
    for lid in sorted(old_lessons.keys() | new_lessons.keys()):
        a = snapshot("before", old_lessons.get(lid), old_assignments)
        b = snapshot("after", new_lessons.get(lid), new_assignments)
        if a == b:
            continue
        if a is None:
            action, counter = "added", "added"
        elif b is None:
            action, counter = "removed", "removed"
        elif a["assignment_id"] != b["assignment_id"] or a["slot"] != b["slot"]:
            action, counter = "moved", "moved"
        elif any(a[field] != b[field] for field in (
            "class_id", "subject_id", "teacher_id", "class_name", "subject_name", "teacher_name",
        )):
            action, counter = "updated", "moved"
        else:
            action, counter = "locked", "locked"
        counts[counter] += 1
        if len(details) < MAX_DETAILS_PER_NOTICE:
            details.append(ScheduleNotificationDetail(
                action="restored" if restored else action, payload_json=encoded({"before": a, "after": b})
            ))
    for key, value in counts.items():
        setattr(notice, f"{key}_count", value)
    notice.details[:] = details
