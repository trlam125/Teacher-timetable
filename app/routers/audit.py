from __future__ import annotations

from fastapi import APIRouter, Body
from app.services.runtime import *

router = APIRouter()


@router.get("/schedule-audit", response_class=HTMLResponse)
def standalone_schedule_audit_page(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    chatbot_project = chatbot_project_for_user(user, db)
    return templates.TemplateResponse(
        "schedule_audit.html",
        {
            "request": request,
            "user": user,
            "greeting_name": user_greeting_name(user),
            "days": DAYS,
            "ai_enabled": bool(os.getenv("GEMINI_API_KEY", "").strip()),
            "ai_primary_model": os.getenv("GEMINI_MODEL", "gemini-3.7-flash").strip()
            or "gemini-3.7-flash",
            **chatbot_ui_context(chatbot_project),
        },
    )


@router.get("/projects/{pid}/schedule-audit")
def legacy_schedule_audit_page(pid: int, user: User = Depends(current_user)):
    # Route cũ chỉ để bookmark cũ không bị lỗi; không đọc bất kỳ dữ liệu project nào.
    return RedirectResponse("/schedule-audit", 303)


@router.post("/api/schedule-audit")
def standalone_audit_schedule_file(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
):
    filename, content = read_schedule_upload(file)
    from app.schedule_audit import (
        ScheduleAuditParseError,
        analyze_standalone_schedule_file,
    )

    try:
        return analyze_standalone_schedule_file(
            filename=filename,
            content=content,
            include_editable=False,
        )
    except ScheduleAuditParseError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
    except Exception:
        logger.exception("standalone schedule audit failed")
        return JSONResponse(
            {
                "ok": False,
                "message": "Không thể phân tích file thời khóa biểu này. Hãy kiểm tra lại cấu trúc file.",
            },
            status_code=500,
        )


@router.get("/api/schedule-audit/limits")
def get_schedule_audit_saved_limits(
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    """Read only this account's saved quotas, independent of a project."""
    import json
    from app.models import ScheduleAuditLimitProfile
    from sqlalchemy import select
    from app.schedule_audit.saved_limits import migrate_saved_draft
    profile = db.scalar(select(ScheduleAuditLimitProfile)
                        .where(ScheduleAuditLimitProfile.user_id == user.id)
                        .with_for_update())
    if profile is None:
        return {"ok": True, "profile": None}
    limits = json.loads(profile.limits_json)
    legacy = "teachers" in limits or any(
        "min" in row or "max" in row
        for section in ("class_subject", "assignments")
        for row in limits.get(section, []) if isinstance(row, dict)
    )
    if legacy:
        limits = migrate_saved_draft(limits)
        profile.limits_json = json.dumps(limits, ensure_ascii=False)
        profile.revision += 1
        db.commit()
    return {"ok": True, "profile": {
        "limits": limits,
        "catalog": json.loads(profile.catalog_json),
        "revision": profile.revision,
        "updated_at": profile.updated_at,
    }}


@router.put("/api/schedule-audit/limits")
def save_schedule_audit_limits(
    payload: dict = Body(...),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    """Persist an explicitly saved draft. Version checking blocks silent overwrite."""
    import json
    from datetime import datetime, timezone
    from app.models import ScheduleAuditLimitProfile
    from app.schedule_audit.saved_limits import clean_limit_draft, clean_import_catalog
    if len(json.dumps(payload, ensure_ascii=False)) > 250_000:
        return JSONResponse({"ok": False, "message": "Dữ liệu định mức quá lớn."}, status_code=400)
    try:
        limits = clean_limit_draft(payload.get("limits"))
        catalog = clean_import_catalog(payload.get("catalog"))
        revision = payload.get("revision", 0)
        if type(revision) is not int or revision < 0:
            raise ValueError("Phiên bản định mức không hợp lệ.")
    except (ValueError, TypeError) as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError
    profile = db.scalar(select(ScheduleAuditLimitProfile)
                        .where(ScheduleAuditLimitProfile.user_id == user.id)
                        .with_for_update())
    current = profile.revision if profile else 0
    if revision != current:
        return JSONResponse({"ok": False,
                             "message": "Bảng định mức đã thay đổi ở phiên làm việc khác. Hãy import lại trước khi lưu."},
                            status_code=409)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if profile is None:
        profile = ScheduleAuditLimitProfile(user_id=user.id, limits_json="{}", catalog_json="{}",
                                            revision=0, updated_at=now)
        db.add(profile)
    profile.limits_json = json.dumps(limits, ensure_ascii=False)
    profile.catalog_json = json.dumps(catalog, ensure_ascii=False)
    profile.updated_at = now
    profile.revision = current + 1
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return JSONResponse({"ok": False,
                             "message": "Bảng ngưỡng vừa được lưu ở nơi khác. Vui lòng import lại."},
                            status_code=409)
    except Exception:
        db.rollback()
        raise
    return {"ok": True, "profile": {"limits": limits, "catalog": catalog,
                                     "revision": profile.revision, "updated_at": now}}


@router.post("/api/schedule-audit/workload")
def standalone_recheck_weekly_load(
    file: UploadFile = File(...),
    report_json: str = Form(...),
    limits_json: str = Form(...),
    user: User = Depends(current_user),
):
    """Check user-entered thresholds against the original file plus edited labels."""
    from app.schedule_audit import (
        ScheduleAuditParseError,
        analyze_standalone_schedule_file,
        apply_standalone_viewer_edits,
    )
    import json
    from app.schedule_audit.custom_limits import check_custom_weekly_workload
    filename, content = read_schedule_upload(file)
    try:
        edited = read_schedule_audit_report_json(report_json)
        limits = json.loads(limits_json)
        source = analyze_standalone_schedule_file(
            filename=filename, content=content, include_editable=False,
        )
        recomputed = apply_standalone_viewer_edits(source, edited)
        workload = check_custom_weekly_workload(recomputed["viewer"], limits)
        return {"ok": True, "workload": workload}
    except (ScheduleAuditParseError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
    except Exception:
        logger.exception("weekly teaching load recheck failed")
        return JSONResponse({"ok": False, "message": "Không thể tính lại số tiết sau khi sửa dữ liệu."}, status_code=500)


@router.post("/api/schedule-audit/ai")
def standalone_ai_audit_schedule_file(
    file: Optional[UploadFile] = File(None),
    report_json: str = Form(""),
    user: User = Depends(current_user),
):
    from app.chatbot import ChatbotError
    from app.schedule_ai import analyze_schedule_with_gemini
    from app.schedule_audit import (
        ScheduleAuditParseError,
        analyze_standalone_schedule_file,
        apply_standalone_viewer_edits,
    )

    if report_json.strip():
        edited_report = read_schedule_audit_report_json(report_json)
        if file is not None:
            filename, content = read_schedule_upload(file)
            try:
                base_report = analyze_standalone_schedule_file(
                    filename=filename,
                    content=content,
                    include_editable=False,
                )
                report = apply_standalone_viewer_edits(base_report, edited_report)
            except ScheduleAuditParseError as exc:
                return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
            except ValueError:
                return JSONResponse(
                    {
                        "ok": False,
                        "message": "Dữ liệu chỉnh sửa không khớp với file thời khóa biểu gốc.",
                    },
                    status_code=400,
                )
            except Exception:
                logger.exception("standalone AI edited schedule rebuild failed")
                return JSONResponse(
                    {
                        "ok": False,
                        "message": "Không thể đối chiếu dữ liệu chỉnh sửa với file thời khóa biểu gốc.",
                    },
                    status_code=500,
                )
        else:
            # Backward-compatible fallback for older clients. Derived fields are
            # still recomputed by read_schedule_audit_report_json().
            report = edited_report
    else:
        if file is None:
            return JSONResponse(
                {"ok": False, "message": "Hãy chọn file thời khóa biểu cần phân tích."},
                status_code=400,
            )
        filename, content = read_schedule_upload(file)
        try:
            report = analyze_standalone_schedule_file(
                filename=filename,
                content=content,
                include_editable=False,
            )
        except ScheduleAuditParseError as exc:
            return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
        except Exception:
            logger.exception("standalone AI schedule audit parse failed")
            return JSONResponse(
                {
                    "ok": False,
                    "message": "Không thể đọc file thời khóa biểu trước khi gửi sang AI.",
                },
                status_code=500,
            )

    try:
        ai_result, model_used, fallback_failures = analyze_schedule_with_gemini(report)
        return {
            "ok": True,
            "report": report,
            "ai": ai_result,
            "model": model_used,
            "fallback_failures": fallback_failures,
        }
    except ChatbotError as exc:
        logger.warning("AI schedule audit failed: %s", exc)
        status_code = 400 if exc.code == "context_too_large" else 503
        return JSONResponse(
            {
                "ok": False,
                "message": str(exc),
                "code": exc.code,
            },
            status_code=status_code,
        )
    except Exception:
        logger.exception("unexpected AI schedule audit failure")
        return JSONResponse(
            {
                "ok": False,
                "message": "Không thể kết nối AI để phân tích thời khóa biểu. Kiểm tra thường vẫn hoạt động bình thường.",
            },
            status_code=503,
        )
