from __future__ import annotations

from app.models import User
from app.services.authentication.sessions import current_user, db_session
from app.services.entities.schemas import GenerateScheduleIn
from app.services.projects import get_project_for_update
from app.services.authentication.permissions import is_super_admin
from app.services.scheduler_diagnostics import build_scheduler_diagnostics
from app.services.schedule_generation import generate_schedule
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional


router = APIRouter()


@router.get("/api/projects/{pid}/scheduler-diagnostics")
def scheduler_diagnostics(
    pid: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_super_admin(user):
        raise HTTPException(403, "Chỉ super admin được xem chẩn đoán bộ xếp")
    # Read the schedule and its stored run from one stable project state.
    project = get_project_for_update(pid, user, db)
    return JSONResponse(build_scheduler_diagnostics(db, project), headers={"Cache-Control": "no-store"})


@router.post("/api/projects/{pid}/generate")
def generate(
    pid: int,
    payload: Optional[GenerateScheduleIn] = None,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    p = get_project_for_update(pid, user, db)
    result = generate_schedule(db, p, pid, payload)
    if not is_super_admin(user) and isinstance(result, dict):
        result.pop("search_diagnostics", None)
    return result
