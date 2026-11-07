from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager

from sqlalchemy import create_engine, delete, insert, select
from sqlalchemy.orm import Session

from app.models import (
    Assignment, Base, Department, FixedLesson, Grade, GradeSubjectRequirement,
    Lesson, Project, School, SchoolClass, Subject, Teacher, TeacherPreference,
    TeacherSubject, User,
)

# Parent-first order is also used for restoration. Snapshots never contain accounts.
MODELS = (Department, Subject, Teacher, TeacherSubject, Grade, GradeSubjectRequirement,
          SchoolClass, Assignment, FixedLesson, Lesson, TeacherPreference)
PROJECT_FIELDS = ("name", "school_name", "days", "sessions", "periods_per_session", "blocked_slots_json")


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value):
    return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()


def capture(db, project):
    return {
        "version": 1,
        "project": {field: getattr(project, field) for field in PROJECT_FIELDS},
        "tables": {
            model.__tablename__: [dict(row) for row in db.execute(
                select(model.__table__).where(model.project_id == project.id).order_by(model.id)
            ).mappings()]
            for model in MODELS
        },
    }


def schedule_unchanged(before, after):
    """Display-only edits may proceed even when the existing timetable has errors."""
    def scheduling_state(state):
        named_tables = {"departments", "subjects", "teachers", "grades", "classes"}
        return {
            "project": {key: value for key, value in state["project"].items()
                        if key not in {"name", "school_name"}},
            "tables": {
                table: [{key: value for key, value in row.items()
                         if table not in named_tables or key not in {"name", "short_name"}}
                        for row in rows]
                for table, rows in state["tables"].items()
            },
        }
    return scheduling_state(before) == scheduling_state(after)


@contextmanager
def simulation(state, project, actor):
    """Run real business rules in an isolated DB; production receives no preview writes."""
    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            user_ids = {actor.id, project.owner_id}
            user_ids.update(row["submitted_by_user_id"] for row in state["tables"]["teacher_preferences"]
                            if row["submitted_by_user_id"] is not None)
            connection.execute(insert(User.__table__), [
                {"id": uid, "email": f"{uid}@preview.invalid", "password_hash": "",
                 "name": actor.name if uid == actor.id else "", "role": "super_admin"}
                for uid in sorted(user_ids)
            ])
            if project.school_id is not None:
                connection.execute(insert(School.__table__).values(id=project.school_id, name=project.school_name))
            values = {column.name: getattr(project, column.name) for column in Project.__table__.columns}
            connection.execute(insert(Project.__table__).values(**values))
            for model in MODELS:
                rows = state["tables"][model.__tablename__]
                if rows:
                    connection.execute(insert(model.__table__), rows)
        with Session(engine, expire_on_commit=False) as sandbox:
            sandbox.info["project_change_managed"] = True
            yield sandbox, sandbox.get(Project, project.id), sandbox.get(User, actor.id)
    finally:
        engine.dispose()


def restore(db, project, state):
    from fastapi import HTTPException
    if state.get("version") != 1:
        raise HTTPException(409, "Định dạng bản dự phòng chưa được hỗ trợ.")
    submitters = {row["submitted_by_user_id"] for row in state["tables"]["teacher_preferences"]
                  if row["submitted_by_user_id"] is not None}
    if submitters and submitters != set(db.scalars(select(User.id).where(User.id.in_(submitters)))):
        raise HTTPException(409, "Bản dự phòng có nguyện vọng thuộc tài khoản đã bị xóa. Không thể phục hồi nguyên trạng.")
    # Never overwrite rows belonging to another project, including IDs reused by SQLite.
    for model in MODELS:
        ids = [row["id"] for row in state["tables"][model.__tablename__]]
        if ids and db.scalar(select(model.id).where(model.id.in_(ids), model.project_id != project.id).limit(1)):
            raise HTTPException(409, "Không thể phục hồi vì mã dữ liệu đã được sử dụng ở project khác.")
    for model in reversed(MODELS):
        db.execute(delete(model).where(model.project_id == project.id))
    db.flush()
    for model in MODELS:
        rows = state["tables"][model.__tablename__]
        if rows:
            db.execute(insert(model.__table__), rows)
    for key in PROJECT_FIELDS:
        setattr(project, key, state["project"][key])
    db.flush()
    db.expire_all()
