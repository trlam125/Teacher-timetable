"""Shared, bounded history for AI and timetable scheduling incidents."""
from __future__ import annotations

import json

from sqlalchemy import delete, select

from app.models import SystemIncidentLog
from app.settings import MAX_SYSTEM_INCIDENT_LOGS
from app.scheduling.solver.diagnostics import scheduler_runtime_diagnostics


def record_system_incident(
    db, *, error_code, message, project_id=None, project_name="", actor=None,
    provider_status=None, details=None,
):
    """Add an incident in the caller's transaction; never commit timetable edits."""
    actor = actor or {}
    text = str(message)[:8000]
    if details:
        text += "\n\n" + json.dumps(details, ensure_ascii=False, indent=2)
    row = SystemIncidentLog(
        project_id=project_id, project_name=str(project_name)[:200],
        user_id=actor.get("id"), user_name=str(actor.get("name") or "")[:120],
        user_email=str(actor.get("email") or "")[:255],
        error_code=str(error_code)[:64], provider_status=provider_status,
        error_message=text[:16000],
    )
    db.add(row)
    db.flush()
    cutoff = db.scalar(select(SystemIncidentLog.id).order_by(
        SystemIncidentLog.id.desc()).offset(MAX_SYSTEM_INCIDENT_LOGS - 1).limit(1))
    if cutoff is not None:
        db.execute(delete(SystemIncidentLog).where(SystemIncidentLog.id < cutoff))
    return row


def record_scheduler_incident(db, context, outcome):
    status = outcome.get("status")
    if status == "complete":
        return None
    return record_system_incident(
        db, error_code=f"scheduler_{status or 'error'}",
        message=outcome.get("message") or "Bộ xếp lịch gặp sự cố.",
        project_id=context["project_id"], project_name=context["project_name"],
        actor=context.get("actor"),
        details={"runtime": scheduler_runtime_diagnostics(),
                 "search": context.get("search"), "outcome": outcome},
    )


def incident_log_view(row):
    """Adapt old plain-text AI entries and new structured scheduler entries."""
    summary, separator, details = row.error_message.partition("\n\n")
    code = row.error_code or "system_error"
    source = "Bộ xếp lịch" if code.startswith("scheduler_") else (
        "Smart TKB" if code.startswith("system_") else "Trợ lý AI"
    )
    return {
        "id": row.id, "created_at": row.created_at,
        "project_id": row.project_id, "project_name": row.project_name,
        "user_name": row.user_name, "user_email": row.user_email,
        "error_code": code, "provider_status": row.provider_status,
        "source_label": source, "summary": summary,
        "details": details if separator else "",
    }
