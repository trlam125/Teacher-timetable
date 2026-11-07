from app.services.change_impact.state import encoded
from app.services.notification_models import ScheduleNotification, ScheduleNotificationDetail


def record_change_notice(db, project, before, after, message, *, restored=False):
    """Also record metadata edits that don't dirty any Lesson ORM rows."""
    notice = db.info.get("_schedule_notification_per_transaction", {}).get(project.id)
    if notice is None:
        notice = ScheduleNotification(project_id=project.id)
        db.add(notice)
    notice.summary_text = message
    old_lessons = {row["id"]: row for row in before["tables"]["lessons"]}
    old_assignments = {row["id"]: row for row in before["tables"]["assignments"]}
    new_assignments = {row["id"]: row for row in after["tables"]["assignments"]}

    def snapshot(state, row, assignments):
        assignment = assignments.get(row["assignment_id"])
        if not assignment:
            return None
        names = {table: {item["id"]: item["name"] for item in state["tables"][table]}
                 for table in ("classes", "subjects", "teachers")}
        return {"assignment_id": row["assignment_id"], "slot": row["slot"], "locked": row["locked"],
                "class_name": names["classes"].get(assignment["class_id"], ""),
                "subject_name": names["subjects"].get(assignment["subject_id"], ""),
                "teacher_name": names["teachers"].get(assignment["teacher_id"], "")}

    count = 0
    for row in after["tables"]["lessons"]:
        previous = old_lessons.get(row["id"])
        if previous is None:
            continue
        a, b = snapshot(before, previous, old_assignments), snapshot(after, row, new_assignments)
        if a == b:
            continue
        notice.details.append(ScheduleNotificationDetail(
            action="restored" if restored else "updated", payload_json=encoded({"before": a, "after": b})
        ))
        count += 1
        if count >= 100:
            break
