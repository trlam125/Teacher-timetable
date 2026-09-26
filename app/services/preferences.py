from __future__ import annotations

from app.services.foundation import *
from app.services.web import *

def teacher_own_preference_payload(
    db: Session, project: Project, user_id: int
) -> list[dict]:
    rows = db.scalars(
        select(TeacherPreference)
        .where(
            TeacherPreference.project_id == project.id,
            TeacherPreference.submitted_by_user_id == user_id,
        )
        .order_by(TeacherPreference.id.desc())
        .limit(10)
    ).all()

    def label(slot: int) -> str:
        day, session, period = slot_meta(project, slot)
        session_text = (
            f"{'Sáng' if session == 0 else 'Chiều'} · " if project.sessions > 1 else ""
        )
        return f"{DAYS[day]} · {session_text}Tiết {period + 1}"

    items = []
    for row in rows:
        preferred = valid_slots(project, parse_slots(row.preferred_json), strict=False)
        unavailable = valid_slots(
            project, parse_slots(row.unavailable_json), strict=False
        )
        items.append(
            {
                "id": row.id,
                "preferred_slots": preferred,
                "unavailable_slots": unavailable,
                "preferred_labels": [label(slot) for slot in preferred],
                "unavailable_labels": [label(slot) for slot in unavailable],
                "note": row.note,
                "status": row.status,
                "created_at": row.created_at,
                "created_at_display": format_vietnam_datetime(row.created_at),
            }
        )
    return items

def preference_payload(db: Session, p: Project):
    rows = db.scalars(
        select(TeacherPreference)
        .where(TeacherPreference.project_id == p.id)
        .order_by(TeacherPreference.id.desc())
    ).all()
    teachers = {
        x.id: x for x in db.scalars(select(Teacher).where(Teacher.project_id == p.id))
    }

    def label(slot: int):
        day, session, period = slot_meta(p, slot)
        session_text = (
            f"{'Sáng' if session == 0 else 'Chiều'} · " if p.sessions > 1 else ""
        )
        return f"{DAYS[day]} · {session_text}Tiết {period + 1}"

    items = []
    for row in rows:
        preferred_slots = valid_slots(p, parse_slots(row.preferred_json), strict=False)
        unavailable_slots = valid_slots(
            p, parse_slots(row.unavailable_json), strict=False
        )
        items.append(
            {
                "id": row.id,
                "teacher_id": row.teacher_id,
                "teacher_name": row.submitted_name
                or (
                    teachers[row.teacher_id].name if row.teacher_id in teachers else "?"
                ),
                "teacher_email": row.submitted_email or "",
                "preferred_slots": preferred_slots,
                "unavailable_slots": unavailable_slots,
                "preferred_labels": [label(slot) for slot in preferred_slots],
                "unavailable_labels": [label(slot) for slot in unavailable_slots],
                "note": row.note,
                "status": row.status,
                "created_at": row.created_at,
                "created_at_display": format_vietnam_datetime(row.created_at),
                "reviewed_at": row.reviewed_at,
                "reviewed_at_display": format_vietnam_datetime(row.reviewed_at),
            }
        )
    return items


__all__ = [name for name in globals() if not name.startswith('__')]
