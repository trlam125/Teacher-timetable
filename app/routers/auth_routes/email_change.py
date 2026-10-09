from __future__ import annotations

import hashlib
import hmac
import secrets
import smtplib
from app.models import EmailChangeVerification, User
from app.services.authentication.credentials import (
    email_change_otp_signer,
    email_change_signer,
    pwd,
)
from app.services.authentication.mail import send_email_change_otp_email
from app.services.authentication.permissions import admin_can_manage_account
from app.services.authentication.rate_limits import rate_limit_exceeded
from app.services.authentication.sessions import current_user, db_session, set_session_cookie
from app.services.authentication.verification import (
    email_change_back_path,
    email_change_confirmation_data,
    email_change_otp_hash,
    email_change_target,
    email_change_verification_for_token,
    mask_email,
)
from app.services.foundation import (
    EMAIL_CHANGE_OTP_MAX_ATTEMPTS,
    EMAIL_CHANGE_OTP_TTL_SECONDS,
    logger,
)
from app.services.web import bounded_text, templates
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typing import Optional


router = APIRouter()


@router.get("/account/email-change", response_class=HTMLResponse)
def email_change_page(
    request: Request,
    project_id: Optional[int] = None,
    user: User = Depends(current_user),
):
    return templates.TemplateResponse(
        "email_change.html",
        {
            "request": request,
            "mode": "start",
            "user": user,
            "target": user,
            "project_id": project_id,
            "error": None,
            "back_path": email_change_back_path(user, project_id),
        },
    )



@router.post("/account/email-change/prepare", response_class=HTMLResponse)
def prepare_email_change(
    request: Request,
    email: str = Form(...),
    current_password: str = Form(""),
    account_id: str = Form(""),
    project_id: Optional[int] = Form(None),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    target = email_change_target(account_id, user, db)
    new_email = bounded_text(email.lower(), "Email mới", 255)
    back_path = email_change_back_path(user, project_id)
    context = {
        "request": request,
        "mode": "start",
        "user": user,
        "target": target,
        "project_id": project_id,
        "error": None,
        "back_path": back_path,
    }
    if "@" not in new_email:
        context["error"] = "Email mới không hợp lệ."
        return templates.TemplateResponse("email_change.html", context, status_code=400)
    if new_email == target.email.lower().strip():
        context["error"] = "Email mới phải khác email hiện tại."
        return templates.TemplateResponse("email_change.html", context, status_code=400)
    if target.id == user.id and (
        not current_password or not pwd.verify(current_password, target.password_hash)
    ):
        context["error"] = "Vui lòng nhập đúng mật khẩu hiện tại trước khi đổi email."
        return templates.TemplateResponse("email_change.html", context, status_code=400)
    if (
        db.scalar(
            select(User.id).where(
                func.lower(User.email) == new_email, User.id != target.id
            )
        )
        is not None
    ):
        context["error"] = "Email mới đã được sử dụng bởi tài khoản khác."
        return templates.TemplateResponse("email_change.html", context, status_code=409)
    confirmation_token = email_change_signer.dumps(
        {
            "actor_id": user.id,
            "account_id": target.id,
            "new_email": new_email,
            "project_id": project_id,
        }
    )
    return templates.TemplateResponse(
        "email_change.html",
        {
            "request": request,
            "mode": "confirm",
            "user": user,
            "target": target,
            "new_email": new_email,
            "confirmation_token": confirmation_token,
            "back_path": back_path,
            "error": None,
        },
    )



@router.post("/account/email-change/confirm", response_class=HTMLResponse)
def confirm_email_change(
    request: Request,
    confirmation_token: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    target, new_email, project_id = email_change_confirmation_data(
        confirmation_token, user, db
    )
    back_path = email_change_back_path(user, project_id)
    if (
        db.scalar(
            select(User.id).where(
                func.lower(User.email) == new_email, User.id != target.id
            )
        )
        is not None
    ):
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "confirm",
                "user": user,
                "target": target,
                "new_email": new_email,
                "confirmation_token": confirmation_token,
                "back_path": back_path,
                "error": "Email mới vừa được tài khoản khác sử dụng.",
            },
            status_code=409,
        )
    if rate_limit_exceeded(
        "email_change_actor", str(user.id), limit=5, window_seconds=15 * 60
    ) or rate_limit_exceeded(
        "email_change_target", new_email, limit=5, window_seconds=15 * 60
    ):
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "confirm",
                "user": user,
                "target": target,
                "new_email": new_email,
                "confirmation_token": confirmation_token,
                "back_path": back_path,
                "error": "Bạn đã yêu cầu đổi email quá nhiều lần. Vui lòng thử lại sau.",
            },
            status_code=429,
        )
    otp = f"{secrets.randbelow(1_000_000):06d}"
    try:
        if not send_email_change_otp_email(new_email, otp):
            raise RuntimeError("SMTP chưa được cấu hình")
    except (OSError, smtplib.SMTPException, RuntimeError, ValueError) as exc:
        logger.exception("Could not send email-change OTP to %s: %s", new_email, exc)
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "confirm",
                "user": user,
                "target": target,
                "new_email": new_email,
                "confirmation_token": confirmation_token,
                "back_path": back_path,
                "error": "Chưa thể gửi OTP tới email mới. Vui lòng thử lại sau.",
            },
            status_code=503,
        )
    old = db.scalar(
        select(EmailChangeVerification)
        .where(EmailChangeVerification.user_id == target.id)
        .with_for_update()
    )
    if old:
        db.delete(old)
        db.flush()
    nonce = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    verification = EmailChangeVerification(
        user_id=target.id,
        requested_by_user_id=user.id,
        new_email=new_email,
        otp_hash=email_change_otp_hash(target.id, new_email, otp),
        token_hash=hashlib.sha256(nonce.encode()).hexdigest(),
        expires_at=(now + timedelta(seconds=EMAIL_CHANGE_OTP_TTL_SECONDS)).isoformat(),
        attempt_count=0,
    )
    db.add(verification)
    db.commit()
    verification_token = email_change_otp_signer.dumps(
        {"id": verification.id, "nonce": nonce}
    )
    return templates.TemplateResponse(
        "email_change.html",
        {
            "request": request,
            "mode": "otp",
            "user": user,
            "target": target,
            "masked_email": mask_email(new_email),
            "verification_token": verification_token,
            "back_path": back_path,
            "error": None,
        },
    )



@router.post("/account/email-change/verify", response_class=HTMLResponse)
def verify_email_change(
    request: Request,
    verification_token: str = Form(...),
    otp: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    verification = email_change_verification_for_token(verification_token, user, db)
    if not verification:
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "expired",
                "user": user,
                "back_path": email_change_back_path(user),
                "error": "Phiên xác minh email không hợp lệ hoặc đã hết hạn.",
            },
            status_code=400,
        )
    target = db.get(User, verification.user_id)
    if not target or (
        target.id != user.id and not admin_can_manage_account(user, target, db)
    ):
        raise HTTPException(403, "Bạn không còn quyền đổi email tài khoản này")
    now = datetime.now(timezone.utc)
    if datetime.fromisoformat(verification.expires_at) <= now:
        db.delete(verification)
        db.commit()
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "expired",
                "user": user,
                "back_path": email_change_back_path(user),
                "error": "Mã OTP đã hết hạn. Hãy bắt đầu lại thao tác đổi email.",
            },
            status_code=400,
        )
    if verification.attempt_count >= EMAIL_CHANGE_OTP_MAX_ATTEMPTS:
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "expired",
                "user": user,
                "back_path": email_change_back_path(user),
                "error": "Bạn đã nhập sai quá số lần cho phép. Hãy bắt đầu lại thao tác đổi email.",
            },
            status_code=429,
        )
    normalized_otp = otp.strip()
    if (
        not normalized_otp.isdigit()
        or len(normalized_otp) != 6
        or not hmac.compare_digest(
            verification.otp_hash,
            email_change_otp_hash(target.id, verification.new_email, normalized_otp),
        )
    ):
        verification.attempt_count += 1
        remaining = max(0, EMAIL_CHANGE_OTP_MAX_ATTEMPTS - verification.attempt_count)
        db.commit()
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "otp",
                "user": user,
                "target": target,
                "masked_email": mask_email(verification.new_email),
                "verification_token": verification_token,
                "back_path": email_change_back_path(user),
                "error": f"Mã OTP không đúng. Bạn còn {remaining} lần thử.",
            },
            status_code=400,
        )
    if (
        db.scalar(
            select(User.id).where(
                func.lower(User.email) == verification.new_email, User.id != target.id
            )
        )
        is not None
    ):
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "expired",
                "user": user,
                "back_path": email_change_back_path(user),
                "error": "Email mới vừa được tài khoản khác sử dụng. Hãy chọn email khác.",
            },
            status_code=409,
        )
    target.email = verification.new_email
    target.session_version += 1
    db.delete(verification)
    db.commit()
    response = templates.TemplateResponse(
        "email_change.html",
        {
            "request": request,
            "mode": "success",
            "user": target if target.id == user.id else user,
            "target": target,
            "back_path": email_change_back_path(user),
            "error": None,
        },
    )
    if target.id == user.id:
        set_session_cookie(response, target)
    return response
