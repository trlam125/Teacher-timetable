"""Shared, bounded history for AI and timetable scheduling incidents."""
from __future__ import annotations

import json
import re

from sqlalchemy import delete, select

from app.models import SystemIncidentLog
from app.settings import MAX_SYSTEM_INCIDENT_LOGS
from app.scheduling.solver.diagnostics import scheduler_runtime_diagnostics


AI_INCIDENT_MESSAGES = {
    "auth": "Nhà cung cấp AI từ chối xác thực hoặc quyền truy cập.",
    "blocked": "Trợ lý AI không thể xử lý nội dung này.",
    "deadline": "Trợ lý AI mất quá nhiều thời gian để trả lời. Hãy thử lại.",
    "empty_response": "Nhà cung cấp AI không trả về câu trả lời.",
    "empty_text": "Câu trả lời của AI không có nội dung văn bản.",
    "invalid_response": "Nhà cung cấp AI trả về dữ liệu sai định dạng.",
    "network": "Không kết nối được tới nhà cung cấp AI.",
    "no_model": "Không có mô hình AI khả dụng.",
    "rate_limit": "Trợ lý AI đang bận. Hãy thử lại sau.",
}
AI_HTTP_MESSAGES = {
    400: "Nhà cung cấp AI từ chối yêu cầu vì dữ liệu gửi đi không hợp lệ.",
    404: "Nhà cung cấp AI không tìm thấy mô hình hoặc điểm truy cập.",
    408: "Nhà cung cấp AI không xử lý yêu cầu trong thời gian cho phép.",
    500: "Nhà cung cấp AI gặp lỗi nội bộ.",
    502: "Cổng kết nối của nhà cung cấp AI nhận được phản hồi lỗi.",
    503: "Dịch vụ của nhà cung cấp AI tạm thời không khả dụng.",
    504: "Cổng kết nối của nhà cung cấp AI chờ phản hồi quá lâu.",
}
LEGACY_MODEL_PREFIX = re.compile(r"^\[model=([^\]\r\n]{1,200})\]\s*")
LEGACY_EXCEPTION_PREFIX = re.compile(r"^([A-Za-z_][A-Za-z0-9_]{0,100}):")


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
    """Read both historical messages and structured incident diagnostics."""
    message, separator, details = row.error_message.partition("\n\n")
    code = row.error_code or "system_error"
    source = "Bộ xếp lịch" if code.startswith("scheduler_") else (
        "Smart TKB" if code.startswith("system_") else "Trợ lý AI"
    )
    summary = message
    technical_message = ""
    metadata = {}
    provider, _, reason = code.partition("_")
    if source == "Trợ lý AI":
        if separator:
            try:
                decoded = json.loads(details)
                if isinstance(decoded, dict):
                    metadata = decoded
            except json.JSONDecodeError:
                pass
        legacy_model = LEGACY_MODEL_PREFIX.match(message)
        if legacy_model:
            metadata.setdefault("model", legacy_model[1])
            message = message[legacy_model.end():]

        summary = message
        if provider in {"gemini", "nvidia"}:
            summary = AI_INCIDENT_MESSAGES.get(reason, "Trợ lý AI chưa thể trả lời. Hãy thử lại sau.")
            if reason == "http" and row.provider_status is not None:
                summary = AI_HTTP_MESSAGES.get(
                    row.provider_status, f"Nhà cung cấp AI trả về HTTP {row.provider_status}.",
                )
            # Older Gemini entries could include provider-controlled text.
            if provider == "gemini" and reason in {"http", "blocked"}:
                message = summary
        elif code == "missing_api_key":
            summary = "Trợ lý AI chưa được cấu hình khóa API."
        elif code == "internal_error":
            summary = "Trợ lý AI gặp lỗi nội bộ."
            legacy_exception = LEGACY_EXCEPTION_PREFIX.match(message)
            if legacy_exception:
                metadata.setdefault("exception_type", legacy_exception[1])
            message = ""
        if message != summary:
            technical_message = message
    return {
        "id": row.id, "created_at": row.created_at,
        "project_id": row.project_id, "project_name": row.project_name,
        "user_name": row.user_name, "user_email": row.user_email,
        "error_code": code, "provider_status": row.provider_status,
        "source_label": source, "summary": summary,
        "technical_message": technical_message,
        "ai_details": metadata,
        "scheduler_details": details if source == "Bộ xếp lịch" else "",
    }
