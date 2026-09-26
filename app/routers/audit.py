from __future__ import annotations

from fastapi import APIRouter
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
            "days": DAYS,
            "ai_enabled": bool(os.getenv("GEMINI_API_KEY", "").strip()),
            "ai_primary_model": os.getenv("GEMINI_MODEL", "gemini-3.7-flash").strip()
            or "gemini-3.7-flash",
            **chatbot_ui_context(chatbot_project),
        },
    )

@router.get("/projects/{pid}/schedule-audit")
def legacy_schedule_audit_page(pid: int, user: User = Depends(current_user)):
    # Route cu chi de bookmark cu khong bi loi; khong doc bat ky du lieu project nao.
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

