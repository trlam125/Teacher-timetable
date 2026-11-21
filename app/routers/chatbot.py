from __future__ import annotations

import json
from uuid import uuid4

from fastapi import (
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.logging_config import logger
from app.models import User
from app.services.authentication.sessions import current_user, db_session
from app.services.projects import chatbot_project_data_for_user, chatbot_ui_context
from app.services.web import templates
from app.settings import MAX_CHATBOT_DOCUMENT_CONTEXT_CHARS, nvidia_primary_model
from app.services.system_incidents import record_system_incident

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
        ask_nvidia,
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

    reference = uuid4().hex[:12].upper()

    def persist_chatbot_failures(failures, *, response_model=None):
        if not failures:
            return
        try:
            actor = {"id": user.id, "name": user.name, "email": user.email}
            for failure in failures:
                record_system_incident(
                    db, project_id=p.id, project_name=p.name, actor=actor,
                    error_code=failure["code"], message=failure["message"],
                    provider_status=failure.get("provider_status"),
                    details={
                        "reference": reference,
                        "model": failure.get("model"),
                        "response_model": response_model,
                        "attempt_count": failure.get("attempt_count"),
                        "retry_failures": failure.get("retry_failures"),
                        "exception_type": failure.get("exception_type"),
                    },
                )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Could not persist chatbot incident %s for project %s", reference, pid)

    try:
        answer, model_used, fallback_failures = ask_nvidia(
            clean_message,
            history,
            chatbot_data,
            document_context or None,
            preferred_model=preferred_model.strip() or None,
        )
        if fallback_failures:
            logger.info("Chatbot incident %s for project %s: answered after fallback", reference, pid)
            persist_chatbot_failures(fallback_failures, response_model=model_used)
    except ChatbotError as exc:
        logger.warning("Chatbot incident %s for project %s: %s", reference, pid, exc.code)
        persist_chatbot_failures(exc.attempts or [{
            "code": exc.code,
            "message": str(exc),
            "model": exc.model_name,
            "provider_status": exc.provider_status,
        }])
        raise HTTPException(503, "Không thể kết nối tới chatbot. Vui lòng thử lại sau.")
    except Exception as exc:
        logger.exception("Unexpected chatbot incident %s for project %s", reference, pid)
        persist_chatbot_failures([{
            "code": "internal_error",
            "message": "Trợ lý AI chưa thể trả lời. Hãy thử lại sau.",
            "exception_type": type(exc).__name__,
        }])
        raise HTTPException(503, "Không thể kết nối tới chatbot. Vui lòng thử lại sau.")
    return {
        "answer": answer,
        "files_analyzed": len(uploaded_tables),
        "document_context": document_context,
        "model_used": model_used,
        "fallback_used": model_used != nvidia_primary_model(),
    }
