from __future__ import annotations

import hashlib
import hmac
import secrets
import smtplib
from app.models import RegistrationVerification, User
from app.services.authentication.captcha import captcha_is_valid, new_captcha
from app.services.authentication.credentials import pwd, registration_signer
from app.services.authentication.mail import send_registration_otp_email
from app.services.authentication.rate_limits import client_rate_limit_key, rate_limit_exceeded
from app.services.authentication.sessions import db_session, set_session_cookie
from app.services.authentication.verification import (
    mask_email,
    registration_otp_context,
    registration_otp_hash,
    registration_verification_for_token,
)
from app.services.foundation import (
    MIN_PASSWORD_LENGTH,
    REGISTRATION_OTP_MAX_ATTEMPTS,
    REGISTRATION_OTP_RESEND_SECONDS,
    REGISTRATION_OTP_TTL_SECONDS,
    logger,
)
from app.services.web import templates
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import Optional


router = APIRouter()


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    captcha_challenge, captcha_token = new_captcha("registration")
    return templates.TemplateResponse(
        "auth.html",
        {
            "request": request,
            "mode": "register",
            "error": None,
            "captcha_challenge": captcha_challenge,
            "captcha_token": captcha_token,
            "form_values": {},
        },
    )



@router.post("/register")
def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    captcha_answer: str = Form(...),
    captcha_token: str = Form(...),
    human_confirm: Optional[str] = Form(None),
    website: str = Form(""),
    db: Session = Depends(db_session),
):
    name = name.strip()
    email = email.lower().strip()
    fresh_challenge, fresh_captcha_token = new_captcha("registration")
    context = {
        "request": request,
        "mode": "register",
        "error": None,
        "captcha_challenge": fresh_challenge,
        "captcha_token": fresh_captcha_token,
        "form_values": {"name": name, "email": email},
    }
    if rate_limit_exceeded(
        "register_ip", client_rate_limit_key(request), limit=12, window_seconds=15 * 60
    ) or rate_limit_exceeded("register_email", email, limit=5, window_seconds=15 * 60):
        context["error"] = (
            "Có quá nhiều yêu cầu đăng ký. Vui lòng đợi vài phút rồi thử lại."
        )
        return templates.TemplateResponse("auth.html", context, status_code=429)
    if (
        website.strip()
        or human_confirm != "yes"
        or not captcha_is_valid(captcha_token, captcha_answer, "registration")
    ):
        context["error"] = (
            "Xác minh bảo mật không hợp lệ hoặc thao tác quá nhanh. Hãy hoàn thành thử thách mới."
        )
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if not name:
        context["error"] = "Tên giáo viên không được để trống"
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if len(name) > 120:
        context["error"] = "Tên giáo viên không được vượt quá 120 ký tự"
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if len(email) > 255:
        context["error"] = "Email không được vượt quá 255 ký tự"
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if len(password) < MIN_PASSWORD_LENGTH:
        context["error"] = f"Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự"
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if password != password_confirm:
        context["error"] = "Hai lần nhập mật khẩu không khớp"
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if not email or "@" not in email:
        context["error"] = "Email không hợp lệ"
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if db.scalar(select(User).where(User.email == email)):
        context["error"] = "Email đã tồn tại"
        return templates.TemplateResponse("auth.html", context, status_code=400)

    now = datetime.now(timezone.utc)
    for expired in db.scalars(
        select(RegistrationVerification).where(
            RegistrationVerification.expires_at <= now.isoformat()
        )
    ).all():
        db.delete(expired)
    db.flush()

    email_verification = db.scalar(
        select(RegistrationVerification)
        .where(RegistrationVerification.email == email)
        .with_for_update()
    )
    if (
        email_verification
        and datetime.fromisoformat(email_verification.resend_available_at) > now
    ):
        context["error"] = (
            "Mã OTP vừa được gửi tới email này. Vui lòng chờ 60 giây trước khi gửi lại."
        )
        return templates.TemplateResponse("auth.html", context, status_code=429)

    otp = f"{secrets.randbelow(1_000_000):06d}"
    nonce = secrets.token_urlsafe(32)
    try:
        if not send_registration_otp_email(email, otp, name):
            raise RuntimeError("SMTP chưa được cấu hình")
    except (OSError, smtplib.SMTPException, RuntimeError, ValueError) as exc:
        logger.exception("Could not send registration OTP to %s: %s", email, exc)
        context["error"] = (
            "Chưa thể gửi mã OTP. Vui lòng kiểm tra email hoặc thử lại sau."
        )
        return templates.TemplateResponse("auth.html", context, status_code=503)

    if email_verification is not None:
        db.delete(email_verification)
        db.flush()
    verification = RegistrationVerification(
        email=email,
        name=name,
        password_hash=pwd.hash(password),
        otp_hash=registration_otp_hash(email, otp),
        token_hash=hashlib.sha256(nonce.encode()).hexdigest(),
        expires_at=(now + timedelta(seconds=REGISTRATION_OTP_TTL_SECONDS)).isoformat(),
        resend_available_at=(
            now + timedelta(seconds=REGISTRATION_OTP_RESEND_SECONDS)
        ).isoformat(),
        attempt_count=0,
    )
    db.add(verification)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        context["error"] = (
            "Email này đang được xác minh ở một phiên khác. Hãy thử lại sau."
        )
        return templates.TemplateResponse("auth.html", context, status_code=409)
    verification_token = registration_signer.dumps(
        {"id": verification.id, "nonce": nonce}
    )
    resend_challenge, resend_captcha = new_captcha("registration_resend")
    return templates.TemplateResponse(
        "auth.html",
        {
            "request": request,
            "mode": "register_otp",
            "error": None,
            "verification_token": verification_token,
            "masked_email": mask_email(email),
            "target_teacher_name": name,
            "captcha_challenge": resend_challenge,
            "captcha_token": resend_captcha,
        },
    )



@router.post("/register/verify", response_class=HTMLResponse)
def verify_registration_otp(
    request: Request,
    verification_token: str = Form(...),
    otp: str = Form(...),
    db: Session = Depends(db_session),
):
    verification = registration_verification_for_token(
        verification_token, db, lock=True
    )
    now = datetime.now(timezone.utc)
    if not verification or datetime.fromisoformat(verification.expires_at) <= now:
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                verification,
                verification_token,
                "Mã OTP không hợp lệ hoặc đã hết hạn. Hãy đăng ký lại.",
            ),
            status_code=400,
        )
    if verification.attempt_count >= REGISTRATION_OTP_MAX_ATTEMPTS:
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                verification,
                verification_token,
                "Bạn đã nhập sai quá số lần cho phép. Hãy gửi lại mã OTP mới.",
            ),
            status_code=429,
        )
    normalized_otp = otp.strip()
    if (
        not normalized_otp.isdigit()
        or len(normalized_otp) != 6
        or not hmac.compare_digest(
            verification.otp_hash,
            registration_otp_hash(verification.email, normalized_otp),
        )
    ):
        verification.attempt_count += 1
        remaining = max(0, REGISTRATION_OTP_MAX_ATTEMPTS - verification.attempt_count)
        db.commit()
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                verification,
                verification_token,
                f"Mã OTP không đúng. Bạn còn {remaining} lần thử.",
            ),
            status_code=400,
        )

    if db.scalar(select(User.id).where(User.email == verification.email)) is not None:
        db.delete(verification)
        db.commit()
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                None,
                verification_token,
                "Email này đã được đăng ký. Hãy chuyển sang trang đăng nhập.",
            ),
            status_code=409,
        )

    teacher_name = verification.name.strip()
    # Đăng ký chỉ tạo tài khoản đăng nhập. Không tạo Teacher trong bất kỳ
    # project nào; hồ sơ giáo viên phục vụ xếp lịch chỉ do quản trị viên tạo/cấu hình.
    user = User(
        name=teacher_name,
        email=verification.email,
        password_hash=verification.password_hash,
        role="teacher",
    )
    db.add(user)
    try:
        db.flush()
        db.delete(verification)
        db.commit()
    except IntegrityError:
        db.rollback()
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                None,
                verification_token,
                "Email này vừa được tài khoản khác sử dụng. Hãy đăng nhập hoặc đăng ký lại.",
            ),
            status_code=409,
        )
    response = RedirectResponse("/teacher", 303)
    set_session_cookie(response, user)
    return response



@router.post("/register/resend", response_class=HTMLResponse)
def resend_registration_otp(
    request: Request,
    verification_token: str = Form(...),
    captcha_answer: str = Form(...),
    captcha_token: str = Form(...),
    human_confirm: Optional[str] = Form(None),
    website: str = Form(""),
    db: Session = Depends(db_session),
):
    verification = registration_verification_for_token(
        verification_token, db, lock=True
    )
    if not verification:
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                None,
                verification_token,
                "Phiên xác minh không còn hợp lệ. Hãy đăng ký lại.",
            ),
            status_code=400,
        )
    if rate_limit_exceeded(
        "register_resend_ip",
        client_rate_limit_key(request),
        limit=10,
        window_seconds=15 * 60,
    ) or rate_limit_exceeded(
        "register_resend_email", verification.email, limit=5, window_seconds=15 * 60
    ):
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                verification,
                verification_token,
                "Bạn đã yêu cầu gửi lại mã quá nhiều lần. Vui lòng đợi rồi thử lại.",
            ),
            status_code=429,
        )
    if (
        website.strip()
        or human_confirm != "yes"
        or not captcha_is_valid(captcha_token, captcha_answer, "registration_resend")
    ):
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                verification,
                verification_token,
                "Xác minh bảo mật không đúng hoặc thao tác quá nhanh.",
            ),
            status_code=400,
        )
    now = datetime.now(timezone.utc)
    if datetime.fromisoformat(verification.resend_available_at) > now:
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                verification,
                verification_token,
                "Vui lòng chờ đủ 60 giây trước khi yêu cầu mã mới.",
            ),
            status_code=429,
        )
    otp = f"{secrets.randbelow(1_000_000):06d}"
    try:
        if not send_registration_otp_email(
            verification.email,
            otp,
            verification.name,
        ):
            raise RuntimeError("SMTP chưa được cấu hình")
    except (OSError, smtplib.SMTPException, RuntimeError, ValueError) as exc:
        logger.exception(
            "Could not resend registration OTP to %s: %s", verification.email, exc
        )
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                verification,
                verification_token,
                "Chưa thể gửi lại mã OTP. Vui lòng thử lại sau.",
            ),
            status_code=503,
        )
    verification.otp_hash = registration_otp_hash(verification.email, otp)
    nonce = secrets.token_urlsafe(32)
    verification.token_hash = hashlib.sha256(nonce.encode()).hexdigest()
    verification.expires_at = (
        now + timedelta(seconds=REGISTRATION_OTP_TTL_SECONDS)
    ).isoformat()
    verification.resend_available_at = (
        now + timedelta(seconds=REGISTRATION_OTP_RESEND_SECONDS)
    ).isoformat()
    verification.attempt_count = 0
    db.commit()
    refreshed_token = registration_signer.dumps({"id": verification.id, "nonce": nonce})
    return templates.TemplateResponse(
        "auth.html",
        registration_otp_context(
            request,
            verification,
            refreshed_token,
        ),
    )
