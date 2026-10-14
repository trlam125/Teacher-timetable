"""School-scoped in-app notifications, now with detailed lesson changes."""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import and_, func, literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import Project, User
from app.services.notification_models import (
    ScheduleNotification, ScheduleNotificationDetail, ScheduleNotificationRead
)
from app.services.authentication.sessions import current_user, db_session
from app.services.auth import is_admin, is_super_admin, user_school_ids

router = APIRouter()


def _authorized_project_ids(db: Session, user: User, project_id: Optional[int]):
    if not (user.role == "teacher" or is_admin(user)):
        raise HTTPException(403, "Access denied")
    query = select(Project.id)
    if not is_super_admin(user):
        schools = user_school_ids(user, db)
        if not schools:
            return []
        query = query.where(Project.school_id.in_(schools))
    if project_id is not None:
        query = query.where(Project.id == project_id)
    ids = db.scalars(query).all()
    if project_id is not None and not ids:
        raise HTTPException(404, "Timetable not found")
    return ids


def _unread_condition(user: User):
    return and_(
        ScheduleNotificationRead.notification_id == ScheduleNotification.id,
        ScheduleNotificationRead.user_id == user.id,
    )


def _summary(row: ScheduleNotification):
    parts = []
    if row.added_count:
        parts.append(f"Th\u00eam {row.added_count} ti\u1ebft")
    if row.removed_count:
        parts.append(f"G\u1ee1 {row.removed_count} ti\u1ebft")
    if row.moved_count:
        parts.append(f"Chuy\u1ec3n {row.moved_count} ti\u1ebft")
    if row.locked_count:
        parts.append(f"\u0110\u1ed5i c\u1ed1 \u0111\u1ecbnh {row.locked_count} ti\u1ebft")
    return ", ".join(parts) + "." if parts else "Th\u1eddi kh\u00f3a bi\u1ec3u \u0111\u00e3 \u0111\u01b0\u1ee3c c\u1eadp nh\u1eadt."


def _total(row):
    return sum(int(x or 0) for x in (
        row.added_count, row.removed_count, row.moved_count, row.locked_count
    ))


def _format_slot(slot, project: Project):
    if slot is None:
        return None
    per_session = max(int(project.periods_per_session or 5), 1)
    sessions = max(int(project.sessions or 2), 1)
    days = max(int(project.days or 6), 1)
    per_day = per_session * sessions
    if not isinstance(slot, int) or slot < 0 or slot >= days * per_day:
        return f"\u00d4 #{slot}"
    day = slot // per_day
    session = (slot % per_day) // per_session
    period = slot % per_session + 1
    day_name = "Ch\u1ee7 nh\u1eadt" if day == 6 else f"Th\u1ee9 {day + 2}"
    session_name = (
        "S\u00e1ng" if session == 0 else "Chi\u1ec1u" if session == 1
        else f"Bu\u1ed5i {session + 1}"
    ) if sessions > 1 else ""
    return " \u00b7 ".join(filter(None, (day_name, session_name, f"Ti\u1ebft {period}")))


def _format_detail(row: ScheduleNotificationDetail, project: Project):
    try:
        payload = json.loads(row.payload_json)
    except (ValueError, TypeError):
        payload = {}
    before = payload.get("before") or None
    after = payload.get("after") or None
    chosen = after or before or {}
    subject = chosen.get("subject_name") or "Ch\u01b0a r\u00f5 m\u00f4n"
    class_name = chosen.get("class_name") or "Ch\u01b0a r\u00f5 l\u1edbp"
    teacher = chosen.get("teacher_name") or "Ch\u01b0a r\u00f5 gi\u00e1o vi\u00ean"
    from_slot = _format_slot(before.get("slot"), project) if before else None
    to_slot = _format_slot(after.get("slot"), project) if after else None
    action = row.action
    labels = {
        "added": "Th\u00eam ti\u1ebft",
        "removed": "G\u1ee1 ti\u1ebft",
        "moved": "Chuy\u1ec3n ti\u1ebft",
        "locked": "\u0110\u1ed5i c\u1ed1 \u0111\u1ecbnh",
    }
    result = {
        "action": action,
        "action_label": labels.get(action, "Thay \u0111\u1ed5i"),
        "class_name": class_name,
        "subject_name": subject,
        "teacher_name": teacher,
        "from_slot": from_slot,
        "to_slot": to_slot,
        "from_assignment": None,
        "locked_before": before.get("locked") if before else None,
        "locked_after": after.get("locked") if after else None,
    }
    if before and after and (
        before.get("assignment_id") != after.get("assignment_id")
        or before.get("teacher_name") != after.get("teacher_name")
        or before.get("class_name") != after.get("class_name")
        or before.get("subject_name") != after.get("subject_name")
    ):
        result["from_assignment"] = {
            "class_name": before.get("class_name"),
            "subject_name": before.get("subject_name"),
            "teacher_name": before.get("teacher_name"),
        }
    return result


@router.get("/api/notifications")
def list_notifications(
    project_id: Optional[int] = None,
    limit: int = Query(25, ge=1, le=50),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    ids = _authorized_project_ids(db, user, project_id)
    if not ids:
        return JSONResponse({"items": [], "unread_count": 0}, headers={"Cache-Control": "no-store"})

    read_join = _unread_condition(user)
    unread = db.scalar(
        select(func.count(ScheduleNotification.id))
        .outerjoin(ScheduleNotificationRead, read_join)
        .where(
            ScheduleNotification.project_id.in_(ids),
            ScheduleNotificationRead.notification_id.is_(None),
        )
    ) or 0
    rows = db.execute(
        select(ScheduleNotification, Project, ScheduleNotificationRead.notification_id)
        .join(Project, Project.id == ScheduleNotification.project_id)
        .outerjoin(ScheduleNotificationRead, read_join)
        .where(ScheduleNotification.project_id.in_(ids))
        .order_by(ScheduleNotification.id.desc())
        .limit(limit)
    ).all()

    # Fetch just one representative lesson per notice, avoiding 100x details
    # on each 12-second polling request.
    preview = {}
    notice_ids = [notice.id for notice, _, _ in rows]
    if notice_ids:
        ranked = select(
            ScheduleNotificationDetail.id.label("id"),
            ScheduleNotificationDetail.notification_id.label("notification_id"),
            func.row_number().over(
                partition_by=ScheduleNotificationDetail.notification_id,
                order_by=ScheduleNotificationDetail.id,
            ).label("rn"),
        ).where(ScheduleNotificationDetail.notification_id.in_(notice_ids)).subquery()
        example_rows = db.execute(
            select(ScheduleNotificationDetail)
            .join(ranked, ranked.c.id == ScheduleNotificationDetail.id)
            .where(ranked.c.rn == 1)
        ).scalars().all()
        preview = {row.notification_id: row for row in example_rows}

    items = []
    for notice, project, read_id in rows:
        example = preview.get(notice.id)
        items.append({
            "id": notice.id,
            "project_id": notice.project_id,
            "project_name": project.name,
            "title": "Th\u1eddi kh\u00f3a bi\u1ec3u \u0111\u00e3 thay \u0111\u1ed5i",
            "message": _summary(notice),
            "change_count": _total(notice),
            "preview": _format_detail(example, project) if example else None,
            "created_at": notice.created_at,
            "is_read": read_id is not None,
            "url": (f"/teacher?project_id={notice.project_id}"
                    if user.role == "teacher" else f"/projects/{notice.project_id}"),
        })
    return JSONResponse({"items": items, "unread_count": unread}, headers={"Cache-Control": "no-store"})


@router.get("/api/notifications/{notification_id}/details")
def notification_details(
    notification_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    notice = db.get(ScheduleNotification, notification_id)
    if not notice or notice.project_id not in _authorized_project_ids(db, user, notice.project_id):
        raise HTTPException(404, "Notification not found")
    project = db.get(Project, notice.project_id)
    if project is None:
        raise HTTPException(404, "Timetable not found")
    details = db.scalars(
        select(ScheduleNotificationDetail)
        .where(ScheduleNotificationDetail.notification_id == notification_id)
        .order_by(ScheduleNotificationDetail.id.asc())
        .limit(100)
    ).all()
    return JSONResponse({
        "id": notification_id,
        "total_count": _total(notice),
        "stored_count": len(details),
        "details": [_format_detail(row, project) for row in details],
    }, headers={"Cache-Control": "no-store"})


@router.post("/api/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    notice = db.get(ScheduleNotification, notification_id)
    if not notice or notice.project_id not in _authorized_project_ids(db, user, notice.project_id):
        raise HTTPException(404, "Notification not found")
    db.execute(
        pg_insert(ScheduleNotificationRead)
        .values(user_id=user.id, notification_id=notice.id)
        .on_conflict_do_nothing(index_elements=["user_id", "notification_id"])
    )
    db.commit()
    return {"ok": True}


@router.post("/api/notifications/read-all")
def mark_all_read(
    project_id: Optional[int] = None,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    ids = _authorized_project_ids(db, user, project_id)
    if not ids:
        return {"ok": True}
    query = select(literal(user.id), ScheduleNotification.id).where(
        ScheduleNotification.project_id.in_(ids)
    )
    db.execute(
        pg_insert(ScheduleNotificationRead)
        .from_select(["user_id", "notification_id"], query)
        .on_conflict_do_nothing(index_elements=["user_id", "notification_id"])
    )
    db.commit()
    return {"ok": True}
