"""Mailbox proof can clear login throttles, but never grants an authenticated session."""
from __future__ import annotations

import hmac
import secrets
import time

from fastapi import HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.config import SECRET_KEY
from app.logging_config import logger
from app.models import LoginUnlockVerification, User
from app.services.authentication.csrf import CSRF_COOKIE, secure_cookies
from app.services.authentication.mail import send_login_unlock_email
from app.services.authentication.rate_limits import client_rate_limit_key, rate_limit_exceeded
from app.services.authentication.sessions import secret_hash, lock_account
from app.services.authentication.verification import mask_email
from app.services.web import templates

UNLOCK_COOKIE = "login_unlock"
UNLOCK_PASS_COOKIE = "login_unlock_pass"
UNLOCK_TTL = 600
UNLOCK_ATTEMPTS = 5


def code_hash(token_hash, code):
    return hmac.new(SECRET_KEY.encode(), f"login-unlock:{token_hash}:{code}".encode(), "sha256").hexdigest()


def browser_hash(request):
    nonce = request.cookies.get(CSRF_COOKIE, "")
    if len(nonce) != 43:
        raise HTTPException(400, "Vui lòng mở lại trang đăng nhập rồi thử lại.")
    return secret_hash(nonce)


def unlock_candidate(request, db):
    token = request.cookies.get(UNLOCK_COOKIE, "")
    if len(token) != 43:
        return None
    row = db.get(LoginUnlockVerification, secret_hash(token))
    if not row or not hmac.compare_digest(row.browser_hash, browser_hash(request)):
        return None
    return row


def take_unlock_pass(request, db, email):
    """One password attempt remains possible even if an attacker relocks the email."""
    token = request.cookies.get(UNLOCK_PASS_COOKIE, "")
    if len(token) != 43:
        return False
    initial = db.get(LoginUnlockVerification, secret_hash(token))
    if not initial or not initial.user_id or initial.email != email:
        return False
    account = lock_account(db, initial.user_id)
    row = db.scalar(select(LoginUnlockVerification).where(LoginUnlockVerification.token_hash == initial.token_hash)
                    .with_for_update().execution_options(populate_existing=True))
    if (not row or not row.verified or row.expires_at <= int(time.time()) or not account
            or row.session_version != account.session_version or account.email != email
            or not hmac.compare_digest(row.browser_hash, browser_hash(request))):
        return False
    db.delete(row)
    db.commit()
    return True


def unlock_page(request, row=None, *, error=None, status=200):
    return templates.TemplateResponse("login_unlock.html", {"request": request,
        "mode": "code" if row else "expired", "masked_email": mask_email(row.email) if row else "",
        "error": error}, status_code=status)


def start_unlock(request, db, email, *, resend=False, password_confirmed=False):
    current = unlock_candidate(request, db)
    now = int(time.time())
    account = db.scalar(select(User).where(User.email == email)) if password_confirmed else None
    current_matches = current and ((account and current.user_id == account.id and current.session_version == account.session_version)
                                   or (not account and current.user_id is None))
    if current_matches and not current.verified and current.email == email and current.expires_at > now:
        if not resend and (not password_confirmed or current.user_id is not None):
            return RedirectResponse("/login/unlock", 303, headers={"Cache-Control": "no-store"})
        if current.resend_available_at > now:
            return unlock_page(request, current, error="Mã vừa được gửi. Vui lòng chờ một phút rồi thử lại.", status=429)
    # Keep this separate from login counters: being locked out cannot lock out
    # recovery, while repeated attacks cannot send unlimited email.
    if (rate_limit_exceeded("unlock_ip", client_rate_limit_key(request), limit=8, window_seconds=900)
            or (password_confirmed and rate_limit_exceeded("unlock_email", email, limit=3, window_seconds=900))):
        return unlock_page(request, current, error="Bạn đã yêu cầu nhiều mã. Vui lòng dùng mã gần nhất hoặc thử lại sau ít phút.", status=429)
    # Knowledge of an email alone must not exhaust that person's email quota.
    # Even with the correct password, the code is still required to unlock.
    token = secrets.token_urlsafe(32)
    otp = f"{secrets.randbelow(1_000_000):06d}"
    # An unknown email gets the same page and cookie, without disclosing accounts.
    row = LoginUnlockVerification(token_hash=secret_hash(token), user_id=account.id if account else None,
        email=email[:255], browser_hash=browser_hash(request), session_version=account.session_version if account else 0,
        otp_hash=code_hash(secret_hash(token), otp), expires_at=now + UNLOCK_TTL,
        resend_available_at=now + 60, attempt_count=0)
    if current_matches and current.email == row.email and current.expires_at > now:
        # Reissuing a code must not reset the total guessing budget for this flow.
        row.attempt_count = current.attempt_count
    if current:
        db.delete(current)
    db.add(row)
    db.commit()
    if account:
        try:
            if not send_login_unlock_email(account.email, otp):
                logger.warning("Login confirmation email could not be delivered")
        except Exception:
            logger.warning("Login confirmation email could not be delivered")
    response = RedirectResponse("/login/unlock", 303, headers={"Cache-Control": "no-store"})
    response.set_cookie(UNLOCK_COOKIE, token, max_age=UNLOCK_TTL,
                        httponly=True, secure=secure_cookies(), samesite="lax")
    return response
