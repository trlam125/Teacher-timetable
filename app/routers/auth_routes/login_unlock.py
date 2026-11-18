from __future__ import annotations

import hmac
import time

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LoginUnlockVerification, User
from app.services.authentication.credentials import signer
from app.services.authentication.csrf import secure_cookies
from app.services.authentication.login_unlock import (
    UNLOCK_ATTEMPTS, UNLOCK_COOKIE, UNLOCK_PASS_COOKIE, code_hash, start_unlock, unlock_candidate, unlock_page,
)
from app.services.authentication.rate_limits import clear_rate_limit_bucket, client_rate_limit_key
from app.services.authentication.sessions import db_session, lock_account
from app.services.authentication.verification import normalize_otp

router = APIRouter()


@router.get("/login/unlock")
def show_unlock(request: Request, db: Session = Depends(db_session)):
    row = unlock_candidate(request, db)
    if not row or row.verified or row.expires_at <= int(time.time()):
        return unlock_page(request, error="Mã đã hết hạn. Vui lòng đăng nhập lại để nhận mã mới.", status=400)
    return unlock_page(request, row)


@router.post("/login/unlock/resend")
def resend_unlock(request: Request, db: Session = Depends(db_session)):
    row = unlock_candidate(request, db)
    if not row or row.verified:
        return unlock_page(request, error="Vui lòng đăng nhập lại để nhận mã mới.", status=400)
    account = db.get(User, row.user_id) if row.user_id else None
    if row.user_id and (not account or account.session_version != row.session_version or account.email != row.email):
        return unlock_page(request, error="Thông tin tài khoản đã thay đổi. Vui lòng đăng nhập lại.", status=400)
    return start_unlock(request, db, row.email, resend=True, password_confirmed=row.user_id is not None)


@router.post("/login/unlock/verify")
def verify_unlock(request: Request, otp: str = Form(""), db: Session = Depends(db_session)):
    initial = unlock_candidate(request, db)
    if not initial:
        return unlock_page(request, error="Vui lòng đăng nhập lại để nhận mã mới.", status=400)
    account = lock_account(db, initial.user_id) if initial.user_id else None
    row = db.scalar(select(LoginUnlockVerification).where(
        LoginUnlockVerification.token_hash == initial.token_hash).with_for_update()
        .execution_options(populate_existing=True))
    if not row or row.verified or row.expires_at <= int(time.time()) or (account and row.session_version != account.session_version):
        return unlock_page(request, error="Mã đã hết hạn. Vui lòng đăng nhập lại để nhận mã mới.", status=400)
    if row.attempt_count >= UNLOCK_ATTEMPTS:
        return unlock_page(request, error="Bạn đã nhập sai nhiều lần. Vui lòng chờ ít phút rồi đăng nhập lại.", status=429)
    code = normalize_otp(otp)
    if not account or account.email != row.email or not code or not hmac.compare_digest(row.otp_hash, code_hash(row.token_hash, code)):
        row.attempt_count += 1
        db.commit()
        return unlock_page(request, row, error="Mã chưa đúng. Vui lòng kiểm tra email rồi nhập lại.", status=400)
    # Email proof clears the account block and this browser's connection block.
    # It does not set a session cookie or bypass the password check.
    clear_rate_limit_bucket("login_email", account.email)
    clear_rate_limit_bucket("login_ip", client_rate_limit_key(request))
    row.verified = True
    row.otp_hash = ""
    row.expires_at = int(time.time()) + 300
    db.commit()
    response = RedirectResponse("/login", 303, headers={"Cache-Control": "no-store"})
    response.delete_cookie(UNLOCK_COOKIE)
    response.set_cookie(UNLOCK_PASS_COOKIE, request.cookies.get(UNLOCK_COOKIE), max_age=300,
                        httponly=True, secure=secure_cookies(), samesite="lax")
    response.set_cookie("login_notice", signer.dumps({"message": "Đã xác nhận email. Bạn có thể đăng nhập lại."}),
                        max_age=120, httponly=True, secure=secure_cookies(), samesite="lax")
    return response
