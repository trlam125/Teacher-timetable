from __future__ import annotations

import hmac
import time

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.services.authentication.csrf import require_form_token
from app.services.authentication.devices import (
    CHALLENGE_TTL, MAX_OTP_ATTEMPTS, begin_login, challenge_page, complete_login,
    otp_digest, pending_login,
    PENDING_COOKIE, cancel_pending_login,
)
from app.services.authentication.sessions import db_session

router = APIRouter()


@router.post("/auth/device/cancel")
def cancel_device_login(request: Request, csrf_token: str = Form(""), db: Session = Depends(db_session)):
    require_form_token(request, csrf_token)
    cancel_pending_login(request, db)
    db.commit()
    response = RedirectResponse("/login", 303, headers={"Cache-Control": "no-store"})
    response.delete_cookie(PENDING_COOKIE)
    return response


@router.get("/auth/device")
def device_page(request: Request, db: Session = Depends(db_session)):
    user, challenge, _ = pending_login(request, db)
    return challenge_page(request, db, user, challenge)


@router.post("/auth/device/verify")
def verify_device(request: Request, otp: str = Form(""), csrf_token: str = Form(""),
                  db: Session = Depends(db_session)):
    require_form_token(request, csrf_token)
    user, challenge, browser = pending_login(request, db)
    if challenge.attempts >= MAX_OTP_ATTEMPTS:
        raise HTTPException(429, "Bạn đã nhập sai 5 lần. Hãy đăng nhập lại để nhận mã mới.")
    if not challenge.verified:
        clean = otp.strip()
        if (not clean.isascii() or not clean.isdigit() or len(clean) != 6
                or not hmac.compare_digest(challenge.otp_hash, otp_digest(challenge.token_hash, clean))):
            challenge.attempts += 1
            db.commit()
            return challenge_page(request, db, user, challenge,
                                  error="Mã xác minh không đúng. Vui lòng kiểm tra lại email.", status=400)
        challenge.verified = True
        db.flush()
    response = complete_login(request, db, user, challenge, browser)
    db.commit()
    return response


@router.post("/auth/device/complete")
def choose_device(request: Request, replace_device_id: str = Form(""), csrf_token: str = Form(""),
                  db: Session = Depends(db_session)):
    require_form_token(request, csrf_token)
    user, challenge, browser = pending_login(request, db)
    return complete_login(request, db, user, challenge, browser, replace_device_id)


@router.post("/auth/device/resend")
def resend_device_code(request: Request, csrf_token: str = Form(""), db: Session = Depends(db_session)):
    require_form_token(request, csrf_token)
    user, challenge, _ = pending_login(request, db)
    if challenge.verified:
        return challenge_page(request, db, user, challenge)
    if int(time.time()) < challenge.expires_at - CHALLENGE_TTL + 60:
        return challenge_page(request, db, user, challenge,
                              error="Vui lòng đợi 60 giây trước khi gửi lại mã.", status=429)
    return begin_login(request, db, user)
