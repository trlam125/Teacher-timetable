from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.models import User
from app.services.authentication.sessions import current_user, db_session
from app.services.projects import (
    get_project,
    project_data,
    project_lessons_data,
    teacher_view_project,
)
from app.services.schedule_live_payload import live_schedule_response
from app.services.schedule_operations.validation import schedule_ui_validation_report

router = APIRouter()


@router.get("/api/projects/{pid}/live")
def live_data(
    pid: int,
    revision: Optional[str] = None,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if user.role == "teacher":
        project = teacher_view_project(user, db, pid)
        if project is None:
            raise HTTPException(404, "Không tìm thấy bộ thời khóa biểu")
        return live_schedule_response(db, project, revision, public=True)
    project = get_project(pid, user, db)
    return live_schedule_response(db, project, revision)


@router.get("/api/projects/{pid}/data")
def api_data(
    pid: int,
    parts: Optional[str] = None,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    p = get_project(pid, user, db)
    requested = {item.strip() for item in (parts or "").split(",") if item.strip()}
    if not requested:
        return project_data(db, p)
    unknown = requested - {"lessons", "schedule_validation"}
    if unknown:
        raise HTTPException(
            400, f"Phần dữ liệu không hỗ trợ: {', '.join(sorted(unknown))}"
        )
    result = {}
    if "lessons" in requested:
        result["lessons"] = project_lessons_data(db, p.id)
    if "schedule_validation" in requested:
        result["schedule_validation"] = schedule_ui_validation_report(db, p)
    return result
