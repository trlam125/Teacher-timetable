"""Log changes to ORM-managed Lessons in the same database transaction.

Keep original totals but also persist up to 100 immutable detail snapshots per
project and transaction. Rollbacks remove notifications and their details.
Direct SQL/bulk ORM updates bypass ORM events and are not covered.
"""
from __future__ import annotations

import json
from collections import defaultdict

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from app.models import Assignment, Lesson, SchoolClass, Subject, Teacher
from app.services.notification_models import ScheduleNotification, ScheduleNotificationDetail

_REGISTERED = False
MAX_DETAILS_PER_NOTICE = 100


def _empty_counts():
    return {"added": 0, "removed": 0, "moved": 0, "locked": 0}


def _previous(attr, current):
    deleted = attr.history.deleted
    return deleted[0] if deleted else current


def _assignment_names(session: Session, assignment_ids: set[int]):
    """Resolve teacher, class, subject with one query, not one query per lesson."""
    if not assignment_ids:
        return {}
    rows = session.execute(
        select(
            Assignment.id, SchoolClass.name, Subject.name, Teacher.name
        )
        .outerjoin(SchoolClass, Assignment.class_id == SchoolClass.id)
        .outerjoin(Subject, Assignment.subject_id == Subject.id)
        .outerjoin(Teacher, Assignment.teacher_id == Teacher.id)
        .where(Assignment.id.in_(assignment_ids))
    ).all()
    return {
        aid: {"class_name": cls or "(Lop da xoa)",
              "subject_name": subject or "(Mon da xoa)",
              "teacher_name": teacher or "(GV da xoa)"}
        for aid, cls, subject, teacher in rows
    }


def _snapshot(assignment_id, slot, locked, names):
    if assignment_id is None:
        return None
    return {
        "assignment_id": int(assignment_id),
        "class_name": names.get(assignment_id, {}).get("class_name", f"Lop #{assignment_id}"),
        "subject_name": names.get(assignment_id, {}).get("subject_name", "Chua ro mon"),
        "teacher_name": names.get(assignment_id, {}).get("teacher_name", "Chua ro GV"),
        "slot": int(slot) if slot is not None else None,
        "locked": bool(locked),
    }


def _before_flush(session: Session, flush_context, instances):
    changes = defaultdict(_empty_counts)
    candidates = []
    assignment_ids = set()

    for lesson in tuple(session.new):
        if not isinstance(lesson, Lesson) or lesson.project_id is None:
            continue
        current_assignment = lesson.assignment_id
        candidates.append((int(lesson.project_id), "added", None,
                           (current_assignment, lesson.slot, lesson.locked)))
        changes[int(lesson.project_id)]["added"] += 1
        if current_assignment is not None:
            assignment_ids.add(int(current_assignment))

    for lesson in tuple(session.deleted):
        if not isinstance(lesson, Lesson) or lesson.project_id is None:
            continue
        current_assignment = lesson.assignment_id
        candidates.append((int(lesson.project_id), "removed",
                           (current_assignment, lesson.slot, lesson.locked), None))
        changes[int(lesson.project_id)]["removed"] += 1
        if current_assignment is not None:
            assignment_ids.add(int(current_assignment))

    for lesson in tuple(session.dirty):
        if not isinstance(lesson, Lesson) or lesson in session.deleted:
            continue
        if lesson.project_id is None:
            continue
        state = inspect(lesson)
        assignment_changed = state.attrs.assignment_id.history.has_changes()
        slot_changed = state.attrs.slot.history.has_changes()
        locked_changed = state.attrs.locked.history.has_changes()
        if not (assignment_changed or slot_changed or locked_changed):
            continue
        action = "moved" if assignment_changed or slot_changed else "locked"
        before = (
            _previous(state.attrs.assignment_id, lesson.assignment_id),
            _previous(state.attrs.slot, lesson.slot),
            _previous(state.attrs.locked, lesson.locked),
        )
        after = (lesson.assignment_id, lesson.slot, lesson.locked)
        candidates.append((int(lesson.project_id), action, before, after))
        changes[int(lesson.project_id)][action] += 1
        for aid in (before[0], after[0]):
            if aid is not None:
                assignment_ids.add(int(aid))

    if not changes:
        return

    # Do not call session.flush() or commit here. This query is read-only.
    names = _assignment_names(session, assignment_ids)
    existing = session.info.setdefault("_schedule_notification_per_transaction", {})
    detailed_count = session.info.setdefault("_schedule_notification_details_per_transaction", {})
    for project_id, counts in changes.items():
        row = existing.get(project_id)
        if row is None:
            row = ScheduleNotification(project_id=project_id)
            session.add(row)
            existing[project_id] = row
        row.added_count = int(row.added_count or 0) + counts["added"]
        row.removed_count = int(row.removed_count or 0) + counts["removed"]
        row.moved_count = int(row.moved_count or 0) + counts["moved"]
        row.locked_count = int(row.locked_count or 0) + counts["locked"]

    for project_id, action, before, after in candidates:
        current_total = detailed_count.get(project_id, 0)
        if current_total >= MAX_DETAILS_PER_NOTICE:
            continue
        payload = {
            "before": _snapshot(*before, names) if before else None,
            "after": _snapshot(*after, names) if after else None,
        }
        existing[project_id].details.append(
            ScheduleNotificationDetail(
                action=action,
                payload_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            )
        )
        detailed_count[project_id] = current_total + 1


def _after_transaction_end(session: Session, transaction):
    if transaction.parent is None:
        session.info.pop("_schedule_notification_per_transaction", None)
        session.info.pop("_schedule_notification_details_per_transaction", None)


def register_schedule_notifications():
    global _REGISTERED
    if _REGISTERED:
        return
    event.listen(Session, "before_flush", _before_flush)
    event.listen(Session, "after_transaction_end", _after_transaction_end)
    _REGISTERED = True
