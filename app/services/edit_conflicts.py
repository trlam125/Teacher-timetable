"""Compare editable state while the caller holds the project write lock."""
from __future__ import annotations

import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select

from app.models import GradeSubjectRequirement, TeacherSubject
from app.scheduling.rules import parse_slots


def edit_token(kind, row, *, subject_ids=(), requirements=()):
    fields = {
        "department": ("name",), "subject": ("name", "short_name"),
        "teacher": ("name", "short_name"), "grade": ("name",),
        "class": ("name", "grade_id"),
        "assignment": ("teacher_id", "class_id", "subject_id", "periods_per_week", "block_mode", "consecutive_pattern"),
    }
    if kind == "availability":
        state = sorted(parse_slots(row.unavailable_json))
    elif kind == "grade_locks":
        state = sorted(parse_slots(row.blocked_slots_json))
    else:
        state = {field: getattr(row, field) for field in fields[kind]}
        if kind == "teacher":
            state["subject_ids"] = sorted(subject_ids)
        elif kind == "grade":
            state["requirements"] = sorted(
                (item.subject_id, item.periods_per_week, item.block_mode) for item in requirements
            )
    encoded = json.dumps([kind, row.project_id, row.id, state], sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def current_edit_token(db, kind, row):
    if kind == "teacher":
        links = db.scalars(select(TeacherSubject.subject_id).where(
            TeacherSubject.project_id == row.project_id, TeacherSubject.teacher_id == row.id,
        )).all()
        return edit_token(kind, row, subject_ids=links)
    if kind == "grade":
        requirements = db.scalars(select(GradeSubjectRequirement).where(
            GradeSubjectRequirement.project_id == row.project_id, GradeSubjectRequirement.grade_id == row.id,
        )).all()
        return edit_token(kind, row, requirements=requirements)
    return edit_token(kind, row)


def require_current_edit(expected, actual):
    if not expected:
        raise HTTPException(428, {"reason": "edit_conflict", "message": "Trang chưa có phiên bản dữ liệu để kiểm tra. Hãy tải lại trang rồi mở lại mục cần sửa."})
    if expected != actual:
        raise HTTPException(409, {"reason": "edit_conflict", "message": "Mục này đã được người khác thay đổi. Bản bạn đang nhập chưa được lưu và vẫn được giữ lại. Hãy đóng mục sửa, cập nhật dữ liệu rồi mở lại để đối chiếu trước khi lưu."})
