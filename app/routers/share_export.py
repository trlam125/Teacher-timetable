from __future__ import annotations

from typing import Optional
from urllib.parse import quote
import io

from fastapi import APIRouter
from fastapi import Depends, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project, User
from app.services.authentication.sessions import current_user, db_session
from app.services.projects import get_project, project_data, public_project_data
from app.services.schedule_live_payload import live_schedule_response
from app.services.schedule_operations.validation import schedule_integrity_report
from app.services.web import templates
from app.settings import DAYS

router = APIRouter()


@router.get("/api/share/{token}/live")
def shared_live(token: str, revision: Optional[str] = None, db: Session = Depends(db_session)):
    project = db.scalar(select(Project).where(Project.share_token == token, Project.deleted_at.is_(None)))
    if project is None:
        raise HTTPException(404, "Liên kết chia sẻ không còn khả dụng")
    return live_schedule_response(db, project, revision, public=True)


@router.get("/share/{token}", response_class=HTMLResponse)
def shared(token: str, request: Request, db: Session = Depends(db_session)):
    p = db.scalar(select(Project).where(Project.share_token == token, Project.deleted_at.is_(None)))
    if not p:
        raise HTTPException(404)
    integrity = schedule_integrity_report(db, p)
    return templates.TemplateResponse(
        "share.html",
        {
            "request": request,
            "p": p,
            "data": public_project_data(db, p),
            "days": DAYS,
            "integrity_warning": integrity["message"]
            if not integrity["valid"] or integrity["partial"]
            else None,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/projects/{pid}/schedule-integrity")
def schedule_integrity(
    pid: int, user: User = Depends(current_user), db: Session = Depends(db_session)
):
    p = get_project(pid, user, db)
    report = schedule_integrity_report(db, p)
    return JSONResponse(
        report,
        status_code=200 if report["valid"] else 409,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/projects/{pid}/export.csv", include_in_schema=False)
def export_csv_legacy(
    pid: int, user: User = Depends(current_user), db: Session = Depends(db_session)
):
    get_project(pid, user, db)
    return RedirectResponse(f"/projects/{pid}/export.xlsx", 303)


@router.get("/projects/{pid}/export.xlsx")
def export_excel(
    pid: int, user: User = Depends(current_user), db: Session = Depends(db_session)
):
    from app.excel_export import build_timetable_workbook

    p = get_project(pid, user, db)
    integrity = schedule_integrity_report(db, p)
    data = project_data(db, p)
    workbook = build_timetable_workbook(p, data, integrity=integrity)

    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    encoded_filename = quote(f"{p.name}.xlsx", safe="")
    disposition = (
        f"attachment; filename=thoi-khoa-bieu.xlsx; filename*=UTF-8''{encoded_filename}"
    )
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": disposition,
            "Cache-Control": "no-store",
        },
    )
