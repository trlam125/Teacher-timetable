from __future__ import annotations

import hashlib
import hmac
from app.config import SECRET_KEY
from app.models import EmailChangeVerification, RegistrationVerification, User
from app.services.authentication.captcha import new_captcha
from app.services.authentication.credentials import (
    email_change_otp_signer,
    email_change_signer,
    registration_signer,
    reset_signer,
)
from app.services.authentication.permissions import admin_can_manage_account
from app.services.foundation import (
    EMAIL_CHANGE_CONFIRM_TTL_SECONDS,
    EMAIL_CHANGE_OTP_TTL_SECONDS,
    REGISTRATION_OTP_TTL_SECONDS,
    RESET_TOKEN_TTL_SECONDS,
)
from datetime import datetime, timezone
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import Optional


def registration_otp_hash(email: str, otp: str) -> str:
    return hmac.new(
        SECRET_KEY.encode(), f"{email}:{otp}".encode(), hashlib.sha256
    ).hexdigest()


def email_change_otp_hash(user_id: int, email: str, otp: str) -> str:
    value = f"email-change:{user_id}:{email.lower().strip()}:{otp}"
    return hmac.new(SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def mask_email(email: str) -> str:
    local, separator, domain = email.partition("@")
    if not separator:
        return "***"
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'*' * max(2, len(local) - len(visible))}@{domain}"


def registration_verification_for_token(
    token: str,
    db: Session,
    *,
    lock: bool = False,
) -> RegistrationVerification | None:
    try:
        data = registration_signer.loads(token, max_age=REGISTRATION_OTP_TTL_SECONDS)
        query = select(RegistrationVerification).where(
            RegistrationVerification.id == int(data["id"])
        )
        if lock:
            query = query.with_for_update()
        verification = db.scalar(query)
        nonce_hash = hashlib.sha256(str(data["nonce"]).encode()).hexdigest()
        if not verification or not hmac.compare_digest(
            verification.token_hash, nonce_hash
        ):
            return None
        return verification
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None


def registration_otp_context(
    request: Request,
    verification: RegistrationVerification | None,
    verification_token: str,
    error: str | None = None,
):
    captcha_challenge, captcha_token = new_captcha("registration_resend")
    return {
        "request": request,
        "mode": "register_otp",
        "error": error,
        "verification_token": verification_token,
        "masked_email": mask_email(verification.email)
        if verification
        else "email của bạn",
        "target_teacher_name": verification.name if verification else None,
        "captcha_challenge": captcha_challenge,
        "captcha_token": captcha_token,
    }


def reset_account_for_token(token: str, db: Session) -> Optional[User]:
    try:
        data = reset_signer.loads(token, max_age=RESET_TOKEN_TTL_SECONDS)
        account = db.get(User, int(data["uid"]))
        nonce_hash = hashlib.sha256(str(data["nonce"]).encode()).hexdigest()
        if not account or not account.reset_token_hash:
            return None
        if not hmac.compare_digest(account.reset_token_hash, nonce_hash):
            return None
        expires_at = datetime.fromisoformat(account.reset_token_expires_at or "")
        if expires_at < datetime.now(timezone.utc):
            return None
        return account
    except (BadSignature, SignatureExpired, KeyError, ValueError, TypeError):
        return None


def email_change_target(account_id: str, actor: User, db: Session) -> User:
    raw = str(account_id or "").strip()
    if not raw:
        return actor
    try:
        target_id = int(raw)
    except ValueError as exc:
        raise HTTPException(400, "Tài khoản cần đổi email không hợp lệ") from exc
    target = db.get(User, target_id)
    if not target or not admin_can_manage_account(actor, target, db):
        raise HTTPException(404, "Không tìm thấy tài khoản trong phạm vi quản lý")
    return target


def email_change_back_path(actor: User, project_id: Optional[int] = None) -> str:
    if actor.role == "teacher":
        return (
            f"/teacher/account?project_id={project_id}"
            if project_id is not None
            else "/teacher/account"
        )
    return "/admin/users"


def email_change_confirmation_data(
    token: str, actor: User, db: Session
) -> tuple[User, str, Optional[int]]:
    try:
        data = email_change_signer.loads(
            token, max_age=EMAIL_CHANGE_CONFIRM_TTL_SECONDS
        )
        if int(data["actor_id"]) != actor.id:
            raise HTTPException(
                403, "Phiên xác nhận đổi email không thuộc tài khoản này"
            )
        target = db.get(User, int(data["account_id"]))
        if not target:
            raise HTTPException(404, "Tài khoản không còn tồn tại")
        if target.id != actor.id and not admin_can_manage_account(actor, target, db):
            raise HTTPException(403, "Bạn không còn quyền đổi email tài khoản này")
        new_email = str(data["new_email"]).lower().strip()
        project_id = data.get("project_id")
        return target, new_email, int(project_id) if project_id is not None else None
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            400, "Phiên xác nhận đổi email không hợp lệ hoặc đã hết hạn"
        ) from exc


def email_change_verification_for_token(
    token: str, actor: User, db: Session
) -> EmailChangeVerification | None:
    try:
        data = email_change_otp_signer.loads(
            token, max_age=EMAIL_CHANGE_OTP_TTL_SECONDS
        )
        row = db.scalar(
            select(EmailChangeVerification)
            .where(EmailChangeVerification.id == int(data["id"]))
            .with_for_update()
        )
        if not row or row.requested_by_user_id != actor.id:
            return None
        nonce_hash = hashlib.sha256(str(data["nonce"]).encode()).hexdigest()
        if not hmac.compare_digest(row.token_hash, nonce_hash):
            return None
        return row
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None
