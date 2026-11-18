from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.logging_config import logger
from app.models import EmailChangeVerification, User
from app.services.authentication.credentials import email_change_otp_signer, email_change_signer
from app.services.authentication.mail import send_email_change_otp_email
from app.services.authentication.permissions import admin_can_manage_account, is_super_admin
from app.services.authentication.rate_limits import rate_limit_exceeded, verify_sensitive_password
from app.services.authentication.sessions import (
    current_user, db_session, invalidate_credential_state, lock_account, require_live_session, set_session_cookie,
)
from app.services.authentication.verification import (
    email_change_back_path, email_change_confirmation_data, email_change_otp_hash,
    email_change_recipient, email_change_target, email_change_verification_for_token, mask_email, normalize_otp,
)
from app.services.web import bounded_text, templates
from app.settings import EMAIL_CHANGE_OTP_MAX_ATTEMPTS, EMAIL_CHANGE_OTP_TTL_SECONDS

router = APIRouter()


def page(request, actor, target, mode, *, error=None, status=200, project_id=None, **extra):
    return templates.TemplateResponse("email_change.html", {
        "request": request, "user": actor, "target": target, "mode": mode,
        "project_id": project_id, "back_path": email_change_back_path(actor, project_id),
        "managed_approval": is_super_admin(actor) and target.id != actor.id,
        "error": error, **extra,
    }, status_code=status)


def locked_accounts(request, db, actor, target):
    for account_id in sorted({actor.id, target.id}):
        lock_account(db, account_id)
    actor = require_live_session(request, db)
    target = db.get(User, target.id)
    if not target or (target.id != actor.id and not admin_can_manage_account(actor, target, db)):
        raise HTTPException(403, "Bạn không có quyền thay đổi tài khoản này.")
    return actor, target


@router.get("/account/email-change")
def email_change_page(request: Request, project_id: Optional[int] = None, user: User = Depends(current_user)):
    return page(request, user, user, "start", project_id=project_id)


@router.post("/account/email-change/prepare")
def prepare_email_change(request: Request, email: str = Form(...), current_password: str = Form(""),
                        account_id: str = Form(""), project_id: Optional[int] = Form(None),
                        user: User = Depends(current_user), db: Session = Depends(db_session)):
    target = email_change_target(account_id, user, db)
    new_email = bounded_text(email.lower(), "Email mới", 255)
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", new_email):
        return page(request, user, target, "start", project_id=project_id,
                    error="Vui lòng nhập địa chỉ email đầy đủ.", status=400)
    if new_email == target.email.lower().strip():
        return page(request, user, target, "start", project_id=project_id,
                    error="Email mới cần khác email hiện tại.", status=400)
    if target.id == user.id and not verify_sensitive_password(request, target, current_password):
        return page(request, user, target, "start", project_id=project_id,
                    error="Mật khẩu hiện tại chưa đúng. Vui lòng nhập lại.", status=400)
    if db.scalar(select(User.id).where(User.email == new_email, User.id != target.id)) is not None:
        return page(request, user, target, "start", project_id=project_id,
                    error="Email này đã được dùng cho tài khoản khác.", status=409)
    token = email_change_signer.dumps({"actor_id": user.id, "account_id": target.id,
        "actor_version": user.session_version, "target_version": target.session_version,
        "new_email": new_email, "project_id": project_id})
    return page(request, user, target, "confirm", project_id=project_id, new_email=new_email,
                confirmation_token=token, masked_email=mask_email(email_change_recipient(user, target, new_email)))


@router.post("/account/email-change/confirm")
def confirm_email_change(request: Request, confirmation_token: str = Form(...),
                         user: User = Depends(current_user), db: Session = Depends(db_session)):
    target, new_email, project_id = email_change_confirmation_data(confirmation_token, user, db)
    if (rate_limit_exceeded("email_change_actor", str(user.id), limit=5, window_seconds=900)
            or rate_limit_exceeded("email_change_target", new_email, limit=5, window_seconds=900)):
        return page(request, user, target, "confirm", project_id=project_id, new_email=new_email,
                    confirmation_token=confirmation_token, error="Bạn đã yêu cầu nhiều mã. Vui lòng thử lại sau ít phút.", status=429)
    user, target = locked_accounts(request, db, user, target)
    # Recheck versions and authority after serializing with account changes.
    target, new_email, project_id = email_change_confirmation_data(confirmation_token, user, db)
    if db.scalar(select(User.id).where(User.email == new_email, User.id != target.id)) is not None:
        return page(request, user, target, "expired", error="Email này vừa được dùng cho tài khoản khác.", status=409)
    old = db.scalar(select(EmailChangeVerification).where(EmailChangeVerification.user_id == target.id).with_for_update())
    if old:
        db.delete(old)
        db.flush()
    otp, nonce = f"{secrets.randbelow(1_000_000):06d}", secrets.token_urlsafe(32)
    recipient = email_change_recipient(user, target, new_email)
    row = EmailChangeVerification(user_id=target.id, requested_by_user_id=user.id,
        new_email=new_email, verification_email=recipient, actor_session_version=user.session_version,
        target_session_version=target.session_version, otp_hash=email_change_otp_hash(target.id, new_email, otp),
        token_hash=hashlib.sha256(nonce.encode()).hexdigest(),
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=EMAIL_CHANGE_OTP_TTL_SECONDS)).isoformat(), attempt_count=0)
    db.add(row)
    db.commit()
    try:
        sent = send_email_change_otp_email(recipient, otp, target_name=target.name, new_email=new_email)
    except Exception:
        sent = False
    if not sent:
        logger.warning("Account email confirmation could not be delivered")
        return page(request, user, target, "confirm", project_id=project_id, new_email=new_email,
                    confirmation_token=confirmation_token, error="Chưa gửi được mã. Vui lòng thử lại sau.", status=503)
    token = email_change_otp_signer.dumps({"id": row.id, "nonce": nonce})
    return page(request, user, target, "otp", masked_email=mask_email(recipient),
                verification_token=token, new_email=new_email)


@router.post("/account/email-change/verify")
def verify_email_change(request: Request, verification_token: str = Form(...), otp: str = Form(...),
                        user: User = Depends(current_user), db: Session = Depends(db_session)):
    initial = email_change_verification_for_token(verification_token, user, db, lock=False)
    if not initial:
        return page(request, user, user, "expired", error="Yêu cầu đã hết hạn. Vui lòng thực hiện lại.", status=400)
    target = db.get(User, initial.user_id)
    if not target:
        raise HTTPException(404, "Không tìm thấy tài khoản.")
    user, target = locked_accounts(request, db, user, target)
    row = email_change_verification_for_token(verification_token, user, db)
    if (not row or datetime.fromisoformat(row.expires_at) <= datetime.now(timezone.utc)
            or row.actor_session_version != user.session_version or row.target_session_version != target.session_version
            or row.verification_email != email_change_recipient(user, target, row.new_email)):
        return page(request, user, target, "expired", error="Yêu cầu đã hết hạn hoặc thông tin đã thay đổi. Vui lòng thực hiện lại.", status=400)
    if row.attempt_count >= EMAIL_CHANGE_OTP_MAX_ATTEMPTS:
        return page(request, user, target, "expired", error="Bạn đã nhập sai nhiều lần. Vui lòng thực hiện lại để nhận mã mới.", status=429)
    code = normalize_otp(otp)
    if not code or not hmac.compare_digest(row.otp_hash, email_change_otp_hash(target.id, row.new_email, code)):
        row.attempt_count += 1
        db.commit()
        return page(request, user, target, "otp", masked_email=mask_email(row.verification_email),
                    verification_token=verification_token, new_email=row.new_email,
                    error="Mã chưa đúng. Vui lòng kiểm tra email rồi nhập lại.", status=400)
    if db.scalar(select(User.id).where(User.email == row.new_email, User.id != target.id)) is not None:
        return page(request, user, target, "expired", error="Email này vừa được dùng cho tài khoản khác.", status=409)
    target.email = row.new_email
    invalidate_credential_state(target)
    db.delete(row)
    response = page(request, user, target, "success")
    try:
        if target.id == user.id:
            set_session_cookie(response, target, request, db)
        else:
            db.commit()
    except IntegrityError:
        db.rollback()
        return page(request, user, target, "expired", error="Email này vừa được dùng cho tài khoản khác.", status=409)
    return response
