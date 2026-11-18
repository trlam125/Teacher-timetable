from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
import hashlib
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.logging_config import logger
from app.models import User
from app.database import SessionLocal
from app.services.authentication.captcha import captcha_is_valid, new_captcha
from app.services.authentication.credentials import pwd, reset_signer
from app.services.authentication.mail import (
    email_delivery_configured,
    send_password_reset_email,
)
from app.services.authentication.rate_limits import client_rate_limit_key, rate_limit_exceeded
from app.services.authentication.sessions import (
    db_session,
    development_reset_links_enabled,
    public_base_url,
    invalidate_credential_state,
    lock_account,
)
from app.services.authentication.verification import reset_account_for_token
from app.services.web import templates
from app.settings import MIN_PASSWORD_LENGTH, RESET_TOKEN_TTL_SECONDS


router = APIRouter()


def _deliver_reset_email(recipient: str, reset_url: str, account_id: int, expected_hash: str):
    """Do not expose SMTP latency/failure as an account-existence oracle."""
    try:
        sent = send_password_reset_email(recipient, reset_url)
    except Exception:
        sent = False
    if not sent:
        from sqlalchemy import update
        with SessionLocal() as db:
            db.execute(update(User).where(User.id == account_id, User.reset_token_hash == expected_hash)
                       .values(reset_token_hash=None, reset_token_expires_at=None))
            db.commit()


@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request):
    captcha_challenge, captcha_token = new_captcha()
    return templates.TemplateResponse(
        "forgot_password.html",
        {
            "request": request,
            "captcha_challenge": captcha_challenge,
            "captcha_token": captcha_token,
            "error": None,
            "submitted": False,
            "dev_reset_link": None,
        },
    )



@router.post("/forgot-password", response_class=HTMLResponse)
def forgot_password(
    request: Request,
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    not_robot: Optional[str] = Form(None),
    captcha_answer: str = Form(...),
    captcha_token: str = Form(...),
    db: Session = Depends(db_session),
):
    normalized_email = email.lower().strip()
    if rate_limit_exceeded(
        "forgot_ip", client_rate_limit_key(request), limit=8, window_seconds=15 * 60
    ) or rate_limit_exceeded(
        "forgot_email", normalized_email, limit=4, window_seconds=30 * 60
    ):
        fresh_challenge, fresh_token = new_captcha()
        return templates.TemplateResponse(
            "forgot_password.html",
            {
                "request": request,
                "captcha_challenge": fresh_challenge,
                "captcha_token": fresh_token,
                "error": "Bạn đã gửi quá nhiều yêu cầu. Vui lòng đợi một lúc rồi thử lại.",
                "submitted": False,
                "dev_reset_link": None,
            },
            status_code=429,
        )
    if not_robot != "yes" or not captcha_is_valid(captcha_token, captcha_answer):
        fresh_challenge, fresh_token = new_captcha()
        return templates.TemplateResponse(
            "forgot_password.html",
            {
                "request": request,
                "captcha_challenge": fresh_challenge,
                "captcha_token": fresh_token,
                "error": "Xác minh trực quan chưa đúng. Vui lòng thử lại.",
                "submitted": False,
                "dev_reset_link": None,
            },
            status_code=400,
        )

    reset_log_id = secrets.token_hex(4)
    dev_reset_link = None
    allow_local_link = development_reset_links_enabled(request)
    email_configured = email_delivery_configured()
    base_url = public_base_url(request)
    logger.info(
        "[forgot:%s] captcha accepted; email_transport_configured=%s base_url_configured=%s",
        reset_log_id,
        email_configured,
        bool(base_url),
    )
    # Check service configuration before looking up the account, so the response
    # cannot disclose whether an email exists and missing config never looks successful.
    if not base_url or not (email_configured or allow_local_link):
        logger.error(
            "Password reset unavailable: configure APP_BASE_URL and the active email transport"
        )
        fresh_challenge, fresh_token = new_captcha()
        return templates.TemplateResponse(
            "forgot_password.html",
            {
                "request": request,
                "captcha_challenge": fresh_challenge,
                "captcha_token": fresh_token,
                "error": "Chức năng đặt lại mật khẩu chưa được cấu hình đầy đủ. "
                "Vui lòng liên hệ quản trị viên để kiểm tra URL công khai và dịch vụ gửi email.",
                "submitted": False,
                "dev_reset_link": None,
            },
            status_code=503,
        )

    account = db.scalar(
        select(User).where(func.lower(func.trim(User.email)) == normalized_email)
    )
    logger.info("[forgot:%s] account_match=%s", reset_log_id, account is not None)
    if account:
        account = lock_account(db, account.id)
        nonce = secrets.token_urlsafe(32)
        account.reset_token_hash = hashlib.sha256(nonce.encode()).hexdigest()
        account.reset_token_expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=RESET_TOKEN_TTL_SECONDS)
        ).isoformat()
        db.commit()
        token = reset_signer.dumps({"uid": account.id, "nonce": nonce})
        reset_url = f"{base_url}/reset-password/{token}"
        if email_configured:
            background_tasks.add_task(_deliver_reset_email, account.email.strip(), reset_url,
                                      account.id, account.reset_token_hash)
        if allow_local_link:
            dev_reset_link = reset_url
    fresh_challenge, fresh_token = new_captcha()
    return templates.TemplateResponse(
        "forgot_password.html",
        {
            "request": request,
            "captcha_challenge": fresh_challenge,
            "captcha_token": fresh_token,
            "error": None,
            "submitted": True,
            "dev_reset_link": dev_reset_link,
        },
    )



@router.get("/reset-password/{token}", response_class=HTMLResponse)
def reset_password_page(
    token: str, request: Request, db: Session = Depends(db_session)
):
    account = reset_account_for_token(token, db)
    return templates.TemplateResponse(
        "reset_password.html",
        {
            "request": request,
            "token": token,
            "valid": account is not None,
            "error": None,
            "success": False,
        },
        status_code=200 if account else 400,
    )



@router.post("/reset-password/{token}", response_class=HTMLResponse)
def reset_password(
    token: str,
    request: Request,
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(db_session),
):
    account = reset_account_for_token(token, db, lock=True)
    error = None
    if not account:
        error = (
            "Liên kết đặt lại mật khẩu không hợp lệ, đã hết hạn hoặc đã được sử dụng."
        )
    elif len(password) < MIN_PASSWORD_LENGTH:
        error = f"Mật khẩu mới phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự."
    elif password != password_confirm:
        error = "Hai lần nhập mật khẩu không khớp."
    if error:
        return templates.TemplateResponse(
            "reset_password.html",
            {
                "request": request,
                "token": token,
                "valid": account is not None,
                "error": error,
                "success": False,
            },
            status_code=400,
        )

    account.password_hash = pwd.hash(password)
    invalidate_credential_state(account)
    db.commit()
    return templates.TemplateResponse(
        "reset_password.html",
        {
            "request": request,
            "token": token,
            "valid": False,
            "error": None,
            "success": True,
        },
    )
