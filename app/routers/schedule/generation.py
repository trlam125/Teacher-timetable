from __future__ import annotations

from app.models import User
from app.services.authentication.sessions import current_user, db_session
from app.services.entities.schemas import GenerateScheduleIn
from app.services.projects import get_project_for_update
from app.services.schedule_generation import generate_schedule
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Optional


router = APIRouter()


@router.post("/api/projects/{pid}/generate")
def generate(
    pid: int,
    payload: Optional[GenerateScheduleIn] = None,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    p = get_project_for_update(pid, user, db)
    return generate_schedule(db, p, pid, payload)
