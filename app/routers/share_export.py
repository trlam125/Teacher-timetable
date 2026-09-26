from __future__ import annotations

from fastapi import APIRouter
from app.services.runtime import *

router = APIRouter()

@router.get("/share/{token}", response_class=HTMLResponse)
def shared(token: str, request: Request, db: Session = Depends(db_session)):
    p = db.scalar(select(Project).where(Project.share_token == token))
    if not p:
        raise HTTPException(404)
    integrity = schedule_integrity_report(db, p)
    if not integrity["valid"]:
        raise HTTPException(409, integrity["message"])
    return templates.TemplateResponse(
        "share.html",
        {"request": request, "p": p, "data": public_project_data(db, p), "days": DAYS},
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
    if not integrity["valid"]:
        return JSONResponse(
            integrity,
            status_code=409,
            headers={"Cache-Control": "no-store"},
        )
    data = project_data(db, p)
    workbook = build_timetable_workbook(p, data)

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

