from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from app.chatbot import (
    ChatbotError,
    GEMINI_MAX_OUTPUT_TOKENS,
    GEMINI_TOTAL_TIMEOUT_SECONDS,
    _call_gemini_model,
    _configured_model_chain,
    _env_int,
    _request_timeout,
    _same_model_retryable,
    _sleep_with_backoff,
)

AI_AUDIT_SYSTEM_INSTRUCTION = """
Bạn là bộ kiểm tra thời khóa biểu trường học. Bạn nhận dữ liệu thời khóa biểu đã được parser đọc từ file import và phải tìm các bất thường mà rule cứng khó phát hiện.

Mục tiêu:
- Phát hiện lịch học/phân công có vẻ bất hợp lý: môn bị dồn quá nhiều trong một ngày, quá nhiều tiết cùng môn liên tiếp, giáo viên dạy quá nhiều tiết liên tục, phân bố môn quá lệch trong tuần, hoặc ô có dấu hiệu parser hiểu sai môn/giáo viên từ raw_text.
- Chỉ đưa ra nhận định theo heuristic. Không tự phát minh quy định của trường, định mức giáo viên, tiết bắt buộc hay điều kiện không có trong dữ liệu.
- Không lặp lại các lỗi cứng đã có trong rule_conflicts như trùng giáo viên, trùng lớp hoặc trùng phòng, trừ khi cần nhắc ngắn gọn để giải thích một bất thường khác.
- Hai tiết liên tiếp của cùng một môn là bình thường và KHÔNG được tự động coi là lỗi. Chỉ cảnh báo khi mức độ dồn/lặp thực sự đáng chú ý.
- Khi nghi parser nhận sai, đối chiếu raw_text với subject và teacher, chú ý tiếng Việt, tên đệm như "Văn", các tiền tố "Cô", "Thầy" và các viết tắt môn học.

Bắt buộc trả về đúng MỘT JSON object, không Markdown, không code fence, theo dạng:
{
  "overview": "Nhận xét tổng quan ngắn gọn bằng tiếng Việt",
  "issues": [
    {
      "severity": "warning" hoặc "suggestion",
      "category": "distribution" | "teacher_load" | "consecutive" | "parser_suspicion" | "other",
      "title": "Tiêu đề ngắn",
      "message": "Giải thích cụ thể dựa trên dữ liệu",
      "suggestion": "Gợi ý kiểm tra/sắp xếp lại, có thể để rỗng nếu không cần",
      "cell_keys": ["slot:class_id"]
    }
  ]
}

Quy tắc cell_keys:
- Chỉ dùng cell_key xuất hiện nguyên văn trong allowed_cell_keys của dữ liệu đầu vào.
- Một vấn đề có thể liên quan nhiều ô thì liệt kê tất cả cell_keys tương ứng.
- Nếu là nhận xét toàn cục và không gắn được vào ô cụ thể, dùng mảng rỗng [].
- Tuyệt đối không tự tạo slot, class_id hoặc cell_key mới.

Ưu tiên ít cảnh báo nhưng có giá trị. Nếu không thấy bất thường đáng chú ý, trả issues=[] và overview nói rõ không phát hiện bất thường đáng chú ý bằng AI.
""".strip()

AI_AUDIT_CONTEXT_LIMIT = 350_000
AI_AUDIT_MAX_ISSUES = 80
_VALID_SEVERITIES = {"warning", "suggestion"}
_VALID_CATEGORIES = {"distribution", "teacher_load", "consecutive", "parser_suspicion", "other"}


def _slot_parts(slot: int, viewer: dict[str, Any]) -> tuple[int, int, int]:
    periods = max(1, int(viewer.get("periods") or 1))
    sessions = max(1, int(viewer.get("sessions") or 1))
    per_day = periods * sessions
    day = int(slot) // per_day
    inside = int(slot) % per_day
    session = inside // periods
    period = (inside % periods) + 1
    return day, session, period


def _day_name(day: int) -> str:
    names = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "CN"]
    return names[day] if 0 <= day < len(names) else f"Ngày {day + 1}"


def _session_name(session: int, sessions: int) -> str:
    if sessions <= 1:
        return ""
    if session == 0:
        return "Sáng"
    if session == 1:
        return "Chiều"
    return f"Buổi {session + 1}"


def _compact_audit_context(report: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    viewer = report.get("viewer") or {}
    classes = viewer.get("classes") or []
    cells = viewer.get("cells") or []
    sessions = max(1, int(viewer.get("sessions") or 1))
    compact_cells: list[dict[str, Any]] = []
    allowed_keys: set[str] = set()

    for cell in cells:
        try:
            slot = int(cell.get("slot"))
            class_id = int(cell.get("class_id"))
        except (TypeError, ValueError):
            continue
        cell_key = f"{slot}:{class_id}"
        allowed_keys.add(cell_key)
        day, session, period = _slot_parts(slot, viewer)
        compact_cells.append({
            "cell_key": cell_key,
            "day": _day_name(day),
            "session": _session_name(session, sessions),
            "period": period,
            "class": str(cell.get("class_name") or "")[:120],
            "subject": str(cell.get("subject_name") or "")[:160],
            "teacher": str(cell.get("teacher_name") or "")[:160],
            "room": str(cell.get("room") or "")[:100],
            "raw_text": str(cell.get("raw_text") or "")[:260],
            "rule_conflicts": [str(code)[:80] for code in (cell.get("conflicts") or [])[:8]],
        })

    rule_issues = []
    for issue in (report.get("issues") or [])[:120]:
        if not isinstance(issue, dict):
            continue
        rule_issues.append({
            "code": str(issue.get("code") or "")[:80],
            "severity": str(issue.get("severity") or "")[:30],
            "message": str(issue.get("message") or issue.get("detail") or "")[:500],
        })

    context = {
        "filename": str(report.get("filename") or "")[:260],
        "schedule": {
            "days": int(viewer.get("days") or 0),
            "sessions": sessions,
            "periods_per_session": int(viewer.get("periods") or 0),
            "classes": [{"id": item.get("id"), "name": str(item.get("name") or "")[:120]} for item in classes],
        },
        "summary": report.get("summary") or {},
        "rule_issues": rule_issues,
        "allowed_cell_keys": sorted(allowed_keys),
        "cells": compact_cells,
    }
    return context, allowed_keys


def _build_ai_payload(context_json: str) -> bytes:
    return json.dumps({
        "systemInstruction": {"parts": [{"text": AI_AUDIT_SYSTEM_INSTRUCTION}]},
        "contents": [{
            "role": "user",
            "parts": [{"text": "DỮ LIỆU THỜI KHÓA BIỂU (JSON):\n" + context_json}],
        }],
        "generationConfig": {
            "maxOutputTokens": GEMINI_MAX_OUTPUT_TOKENS,
            "responseMimeType": "application/json",
        },
    }, ensure_ascii=False).encode("utf-8")


def _extract_json_object(answer: str) -> dict[str, Any]:
    text = str(answer or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ChatbotError(
                "AI trả về kết quả không đúng định dạng JSON.",
                code="gemini_invalid_response",
                retry_with_fallback=True,
            )
        try:
            parsed = json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            raise ChatbotError(
                "AI trả về kết quả không đúng định dạng JSON.",
                code="gemini_invalid_response",
                retry_with_fallback=True,
            ) from exc
    if not isinstance(parsed, dict):
        raise ChatbotError(
            "AI trả về kết quả không đúng cấu trúc cần thiết.",
            code="gemini_invalid_response",
            retry_with_fallback=True,
        )
    return parsed


def _sanitize_ai_result(raw: dict[str, Any], allowed_keys: set[str]) -> dict[str, Any]:
    overview = str(raw.get("overview") or "").strip()[:1800]
    issues: list[dict[str, Any]] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()

    raw_issues = raw.get("issues")
    if not isinstance(raw_issues, list):
        raw_issues = []
    for item in raw_issues[:AI_AUDIT_MAX_ISSUES * 2]:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "suggestion").strip().lower()
        if severity not in _VALID_SEVERITIES:
            severity = "suggestion"
        category = str(item.get("category") or "other").strip().lower()
        if category not in _VALID_CATEGORIES:
            category = "other"
        title = str(item.get("title") or "Cần xem lại").strip()[:180]
        message = str(item.get("message") or "").strip()[:900]
        suggestion = str(item.get("suggestion") or "").strip()[:700]
        if not message and not suggestion:
            continue

        raw_keys = item.get("cell_keys")
        if isinstance(raw_keys, str):
            raw_keys = [raw_keys]
        if not isinstance(raw_keys, list):
            raw_keys = []
        cell_keys: list[str] = []
        for key in raw_keys[:40]:
            clean = str(key or "").strip()
            if clean in allowed_keys and clean not in cell_keys:
                cell_keys.append(clean)

        dedupe_key = (title.casefold(), message.casefold(), tuple(cell_keys))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        issues.append({
            "severity": severity,
            "category": category,
            "title": title,
            "message": message,
            "suggestion": suggestion,
            "cell_keys": cell_keys,
        })
        if len(issues) >= AI_AUDIT_MAX_ISSUES:
            break

    warning_count = sum(1 for item in issues if item["severity"] == "warning")
    suggestion_count = len(issues) - warning_count
    if not overview:
        overview = (
            "AI không phát hiện bất thường đáng chú ý trong thời khóa biểu."
            if not issues
            else f"AI phát hiện {len(issues)} điểm nên xem lại."
        )
    return {
        "overview": overview,
        "issues": issues,
        "summary": {
            "total": len(issues),
            "warnings": warning_count,
            "suggestions": suggestion_count,
            "marked_cells": len({key for item in issues for key in item["cell_keys"]}),
        },
    }


def analyze_schedule_with_gemini(
    report: dict[str, Any],
    preferred_model: str | None = None,
) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ChatbotError(
            "Chức năng AI chưa được cấu hình GEMINI_API_KEY trên máy chủ.",
            code="missing_api_key",
        )

    context, allowed_keys = _compact_audit_context(report)
    context_json = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    if len(context_json) > AI_AUDIT_CONTEXT_LIMIT:
        raise ChatbotError(
            "Thời khóa biểu quá lớn để gửi cho AI trong một lần. Kiểm tra rule thường vẫn có thể sử dụng bình thường.",
            code="context_too_large",
        )
    payload = _build_ai_payload(context_json)

    models = _configured_model_chain()
    if preferred_model and preferred_model in models and preferred_model != models[0]:
        models = [models[0], preferred_model, *[model for model in models[1:] if model != preferred_model]]
    retries_per_model = _env_int("GEMINI_ATTEMPTS_PER_MODEL", 2, 1, 4)
    # Keep the same provider deadline budget as the chatbot without coupling the
    # audit endpoint to the chatbot's conversation/history behavior.
    deadline = time.monotonic() + GEMINI_TOTAL_TIMEOUT_SECONDS
    attempts: list[dict[str, Any]] = []

    for model_index, model in enumerate(models):
        last_error: ChatbotError | None = None
        calls_for_model = 0
        for retry_index in range(retries_per_model):
            try:
                raw_result = _call_gemini_model(
                    model,
                    api_key,
                    payload,
                    timeout_seconds=_request_timeout(deadline, model),
                )
                calls_for_model += 1
                if isinstance(raw_result, tuple):
                    answer = str(raw_result[0] or "")
                else:
                    answer = str(raw_result or "")
                parsed = _extract_json_object(answer)
                return _sanitize_ai_result(parsed, allowed_keys), model, attempts
            except ChatbotError as exc:
                calls_for_model += 1 if getattr(exc, "provider_call_count", 0) == 0 else 0
                exc.model_name = exc.model_name or model
                last_error = exc
                can_retry_same = (
                    exc.retry_with_fallback
                    and _same_model_retryable(exc)
                    and retry_index + 1 < retries_per_model
                )
                if can_retry_same:
                    _sleep_with_backoff(retry_index, deadline=deadline)
                    continue
                break

        if last_error is None:
            continue
        attempts.append({
            "model": model,
            "code": str(last_error.code),
            "provider_status": last_error.provider_status,
            "message": str(last_error),
            "attempt_count": calls_for_model,
        })
        has_next = model_index + 1 < len(models)
        if not last_error.retry_with_fallback or not has_next:
            last_error.attempts = attempts
            raise last_error
        _sleep_with_backoff(0, deadline=deadline)

    raise ChatbotError(
        "Không có model Gemini khả dụng để phân tích thời khóa biểu.",
        code="gemini_no_model",
        attempts=attempts,
    )
