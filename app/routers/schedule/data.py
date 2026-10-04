from __future__ import annotations

from fastapi import APIRouter
from app.services.runtime import *

router = APIRouter()


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
