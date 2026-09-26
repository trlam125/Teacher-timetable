from __future__ import annotations

from fastapi import APIRouter
from app.services.runtime import *

router = APIRouter()

@router.get("/projects/{pid}/chatbot", response_class=HTMLResponse)
def chatbot_page(
    pid: int,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    p, _ = chatbot_project_data_for_user(pid, user, db)
    return templates.TemplateResponse(
        "chatbot.html",
        {
            "request": request,
            "user": user,
            "p": p,
            **chatbot_ui_context(p),
        },
    )

@router.post("/api/projects/{pid}/chatbot")
def chatbot_reply(
    pid: int,
    message: str = Form(...),
    history_json: str = Form("[]"),
    document_context_json: str = Form("[]"),
    preferred_model: str = Form(""),
    files: list[UploadFile] | None = File(None),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    from app.chatbot import (
        MAX_TOTAL_UPLOAD_BYTES,
        MAX_UPLOAD_BYTES,
        MAX_UPLOAD_FILES,
        ChatbotError,
        ask_gemini,
        parse_uploaded_table,
    )

    p, chatbot_data = chatbot_project_data_for_user(pid, user, db)
    clean_message = message.strip()
    if not clean_message:
        raise HTTPException(400, "Hãy nhập nội dung cần tư vấn")
    if len(clean_message) > 4000:
        raise HTTPException(400, "Nội dung không được vượt quá 4.000 ký tự")
    try:
        raw_history = json.loads(history_json)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(400, "Lịch sử trò chuyện không hợp lệ")
    if not isinstance(raw_history, list):
        raise HTTPException(400, "Lịch sử trò chuyện không hợp lệ")
    history = []
    for item in raw_history[-8:]:
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
            continue
        content = str(item.get("content", "")).strip()
        if content:
            history.append({"role": item["role"], "content": content[:8000]})

    if len(document_context_json) > MAX_CHATBOT_DOCUMENT_CONTEXT_CHARS:
        raise HTTPException(
            400,
            "Ngữ cảnh tệp của cuộc trò chuyện quá lớn. Hãy xóa cuộc trò chuyện và đính kèm lại tệp cần dùng.",
        )
    try:
        retained_documents = json.loads(document_context_json)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(400, "Ngữ cảnh tệp của cuộc trò chuyện không hợp lệ")
    if not isinstance(retained_documents, list) or any(
        not isinstance(item, dict) for item in retained_documents
    ):
        raise HTTPException(400, "Ngữ cảnh tệp của cuộc trò chuyện không hợp lệ")

    upload_items = [item for item in (files or []) if item.filename]
    if len(upload_items) > MAX_UPLOAD_FILES:
        raise HTTPException(400, f"Chỉ được đính kèm tối đa {MAX_UPLOAD_FILES} tệp")
    uploaded_tables = []
    total_upload_bytes = 0
    for file in upload_items:
        content = file.file.read(MAX_UPLOAD_BYTES + 1)
        total_upload_bytes += len(content)
        if total_upload_bytes > MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(400, "Tổng dung lượng tệp vượt quá giới hạn 12 MB")
        try:
            uploaded_tables.append(parse_uploaded_table(file.filename, content))
        except ChatbotError as exc:
            raise HTTPException(400, str(exc))

    document_map = {}
    for document in [*retained_documents, *uploaded_tables]:
        filename = str(document.get("filename", "")).strip()[:200]
        document_type = str(document.get("type", "")).strip()[:20]
        if not filename or not document_type:
            continue
        document_map[(filename, document_type)] = document
    document_context = list(document_map.values())
    if (
        len(json.dumps(document_context, ensure_ascii=False, separators=(",", ":")))
        > MAX_CHATBOT_DOCUMENT_CONTEXT_CHARS
    ):
        raise HTTPException(
            400,
            "Ngữ cảnh tệp của cuộc trò chuyện quá lớn. Hãy xóa cuộc trò chuyện và chỉ đính kèm các tệp cần thiết.",
        )

    def persist_chatbot_failure(
        error_code: str, error_message: str, provider_status: int | None = None
    ) -> None:
        try:
            db.add(
                ChatbotErrorLog(
                    project_id=p.id,
                    project_name=p.name,
                    user_id=user.id,
                    user_name=user.name,
                    user_email=user.email,
                    error_code=error_code[:64],
                    provider_status=provider_status,
                    error_message=error_message[:8000],
                )
            )
            db.commit()
            cutoff_id = db.scalar(
                select(ChatbotErrorLog.id)
                .order_by(ChatbotErrorLog.id.desc())
                .offset(MAX_CHATBOT_ERROR_LOGS - 1)
                .limit(1)
            )
            if cutoff_id is not None:
                db.execute(
                    delete(ChatbotErrorLog).where(ChatbotErrorLog.id < cutoff_id)
                )
                db.commit()
        except Exception:
            db.rollback()
            logger.exception("Could not persist chatbot error log for project %s", pid)

    try:
        answer, model_used, fallback_failures = ask_gemini(
            clean_message,
            history,
            chatbot_data,
            document_context or None,
            preferred_model=preferred_model.strip() or None,
        )
        for failure in fallback_failures:
            persist_chatbot_failure(
                str(failure.get("code") or "chatbot_error"),
                f"[model={failure.get('model') or 'unknown'}] {failure.get('message') or ''}",
                failure.get("provider_status"),
            )
    except ChatbotError as exc:
        logger.warning("Chatbot request failed for project %s: %s", pid, exc)
        attempts = list(getattr(exc, "attempts", []) or [])
        if attempts:
            for failure in attempts:
                persist_chatbot_failure(
                    str(failure.get("code") or "chatbot_error"),
                    f"[model={failure.get('model') or 'unknown'}] {failure.get('message') or ''}",
                    failure.get("provider_status"),
                )
        else:
            model_name = getattr(exc, "model_name", None)
            prefix = f"[model={model_name}] " if model_name else ""
            persist_chatbot_failure(
                str(getattr(exc, "code", "chatbot_error")),
                f"{prefix}{exc}",
                getattr(exc, "provider_status", None),
            )
        raise HTTPException(503, "Không thể kết nối tới chatbot. Vui lòng thử lại sau.")
    except Exception as exc:
        logger.exception("Unexpected chatbot failure for project %s", pid)
        persist_chatbot_failure(
            "internal_error",
            f"{type(exc).__name__}: {exc}",
        )
        raise HTTPException(503, "Không thể kết nối tới chatbot. Vui lòng thử lại sau.")
    return {
        "answer": answer,
        "files_analyzed": len(uploaded_tables),
        "document_context": document_context,
        "model_used": model_used,
        "fallback_used": model_used
        != (
            os.getenv("GEMINI_MODEL", "gemini-3.7-flash").strip() or "gemini-3.7-flash"
        ),
    }

