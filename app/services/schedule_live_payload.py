from __future__ import annotations

from fastapi.responses import JSONResponse

from app.services.projects import project_data, public_project_data
from app.services.schedule_live import schedule_revision
from app.services.schedule_operations.validation import schedule_integrity_report


def live_schedule_response(db, project, known_revision: str | None, *, public: bool = False):
    revision = schedule_revision(db, project.id)
    headers = {"Cache-Control": "no-store"}
    if known_revision == revision:
        return JSONResponse({"revision": revision, "changed": False}, headers=headers)
    # Authorization may have loaded this ORM object before another request
    # renamed the project or changed its dimensions. Refresh it inside the
    # revision bracket as well as reading its child rows.
    db.refresh(project)
    payload = public_project_data(db, project) if public else project_data(db, project)
    integrity = schedule_integrity_report(db, project) if public else None
    latest_revision = schedule_revision(db, project.id)
    # READ COMMITTED can observe a commit between independent SELECTs. Never
    # label a mixed snapshot as applied; the client retries with its old token.
    if latest_revision != revision or payload["schedule_revision"] != revision:
        return JSONResponse({"revision": latest_revision, "changed": True, "retry": True}, headers=headers)
    return JSONResponse({
        "revision": revision, "changed": True, "data": payload,
        "integrity_warning": integrity["message"] if integrity and (not integrity["valid"] or integrity["partial"]) else None,
    }, headers=headers)
