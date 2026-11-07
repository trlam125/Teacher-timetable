"""Transactional schedule revisions and commit-only realtime invalidation."""
from __future__ import annotations

import json
import secrets
import time

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.models import Base, Project, RealtimeEvent, User, UserSchool
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column


class ScheduleLiveRevision(Base):
    __tablename__ = "schedule_live_revisions"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    revision: Mapped[str] = mapped_column(String(32))


_REGISTERED = False
_PENDING = "_schedule_live_pending"
_WATCHED = {
    "projects", "departments", "subjects", "teachers", "teacher_subjects", "grades",
    "grade_subject_requirements", "classes", "assignments", "lessons", "fixed_lessons",
}


def schedule_revision(db: Session, project_id: int) -> str:
    return db.scalar(select(ScheduleLiveRevision.revision).where(ScheduleLiveRevision.project_id == project_id)) or "0"


def _publish_in_transaction(connection, project_id: int, school_id: int | None, revision: str):
    """All workers, including this one, receive NOTIFY after this commit only."""
    if connection.dialect.name != "postgresql":
        return
    members = select(User.id).join(UserSchool, UserSchool.user_id == User.id).where(
        UserSchool.school_id == school_id, User.role.in_(("admin", "teacher")),
    )
    super_admins = select(User.id).where(User.role == "super_admin")
    recipients = sorted(set(connection.execute(members.union(super_admins)).scalars()))
    if not recipients:
        return
    envelope = json.dumps({
        # Different from every worker's instance_id so its own listener also
        # delivers the event. The manager still handles cross-worker fanout.
        "source": "schedule-live",
        "payload": {"type": "schedule_changed", "project_id": project_id, "revision": revision},
        "exclude_user_id": None, "only_user_ids": recipients,
    }, separators=(",", ":"))
    if len(envelope.encode("utf-8")) > 7000:
        event_id = secrets.token_hex(16)
        connection.execute(RealtimeEvent.__table__.insert().values(
            id=event_id, envelope_json=envelope, expires_at=int(time.time()) + 86400,
        ))
        envelope = json.dumps({"source": "schedule-live", "event_id": event_id})
    connection.exec_driver_sql("SELECT pg_notify(%s, %s)", ("smart_tkb_realtime_v1", envelope))


def _mark_projects(connection, project_ids):
    if not project_ids:
        return
    projects = connection.execute(select(Project.id, Project.school_id).where(Project.id.in_(set(project_ids)))).all()
    if connection.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    for project_id, school_id in projects:
        revision = secrets.token_hex(16)
        statement = insert(ScheduleLiveRevision).values(project_id=project_id, revision=revision)
        connection.execute(statement.on_conflict_do_update(
            index_elements=[ScheduleLiveRevision.project_id], set_={"revision": revision},
        ))
        _publish_in_transaction(connection, project_id, school_id, revision)


def _before_flush(session, _context, _instances):
    pending = session.info.setdefault(_PENDING, [])
    for row in set(session.new) | set(session.dirty) | set(session.deleted):
        if getattr(row, "__tablename__", None) not in _WATCHED:
            continue
        if row in session.dirty and not session.is_modified(row, include_collections=False):
            continue
        pending.append(row)


def _after_flush(session, _context):
    rows = session.info.pop(_PENDING, [])
    ids = {row.id if isinstance(row, Project) else row.project_id for row in rows}
    _mark_projects(session.connection(), {project_id for project_id in ids if project_id is not None})


def _bulk_mutation(state):
    if not (state.is_update or state.is_delete or state.is_insert):
        return state.invoke_statement()
    statement = state.statement
    table = getattr(statement, "table", None)
    if table is None or table.name not in _WATCHED:
        return state.invoke_statement()
    column = table.c.id if table.name == "projects" else table.c.project_id
    if state.is_insert:
        values = state.parameters or [statement.compile().params]
        values = values if isinstance(values, list) else [values]
        ids = {params.get(column.name) for params in values if params.get(column.name) is not None}
    else:
        query = select(column).distinct()
        if statement.whereclause is not None:
            query = query.where(statement.whereclause)
        ids = set(state.session.connection().execute(query, state.parameters or {}).scalars())
    result = state.invoke_statement()
    _mark_projects(state.session.connection(), ids)
    return result


def _end_transaction(session, transaction):
    if transaction.parent is None:
        session.info.pop(_PENDING, None)


def register_schedule_live():
    global _REGISTERED
    if _REGISTERED:
        return
    event.listen(Session, "before_flush", _before_flush)
    event.listen(Session, "after_flush_postexec", _after_flush)
    event.listen(Session, "do_orm_execute", _bulk_mutation, retval=True)
    event.listen(Session, "after_transaction_end", _end_transaction)
    _REGISTERED = True
