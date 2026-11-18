"""Email verification and an account-row-serialized two-browser limit."""
from __future__ import annotations

from datetime import datetime, timezone
import hmac
import secrets
import smtplib
import time

from fastapi import HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select

from app.config import SECRET_KEY
from app.models import AccountDevice, DeviceLoginChallenge
from app.services.authentication.csrf import secure_cookies
from app.services.authentication.mail import send_device_login_otp_email
from app.services.authentication.navigation import after_login_redirect
from app.services.authentication.permissions import is_admin
from app.services.authentication.rate_limits import client_rate_limit_key, rate_limit_exceeded
from app.services.authentication.sessions import (
    DEVICE_COOKIE, DEVICE_COOKIE_TTL, browser_secret, lock_account, secret_hash, set_session_cookie,
)
from app.services.authentication.verification import mask_email
from app.services.web import templates

PENDING_COOKIE = "device_login"
CHALLENGE_TTL = 10 * 60
MAX_DEVICES = 2
MAX_OTP_ATTEMPTS = 5


def device_label(request):
    ua = request.headers.get("user-agent", "")[:1024]
    browser = next((name for marker, name in (("Edg", "Edge"), ("OPR/", "Opera"),
        ("Firefox/", "Firefox"), ("FxiOS/", "Firefox"), ("Chrome/", "Chrome"),
        ("CriOS/", "Chrome"), ("Safari/", "Safari")) if marker in ua), "Trình duyệt")
    platform = next((name for marker, name in (("Android", "Android"), ("iPhone", "iPhone"),
        ("iPad", "iPad"), ("Windows", "Windows"), ("Macintosh", "macOS"),
        ("Linux", "Linux")) if marker in ua), "Thiết bị khác")
    return f"{browser} trên {platform}"


def otp_digest(token_hash, otp):
    return hmac.new(SECRET_KEY.encode(), f"device-login:{token_hash}:{otp}".encode(), "sha256").hexdigest()


def device_rows(db, user_id):
    return db.scalars(select(AccountDevice).where(AccountDevice.user_id == user_id)
                      .order_by(AccountDevice.last_used_at.desc(), AccountDevice.id)).all()


def challenge_page(request, db, user, challenge, *, error=None, status=200):
    devices = [{"id": row.id, "label": row.label,
                "last_used": datetime.fromtimestamp(row.last_used_at, timezone.utc).isoformat()}
               for row in device_rows(db, user.id)] if challenge.verified else []
    return templates.TemplateResponse("device_login.html", {
        "request": request, "masked_email": mask_email(user.email), "error": error,
        "mode": "choose" if challenge.verified else "otp", "devices": devices,
    }, status_code=status, headers={"Referrer-Policy": "no-referrer"})


def _finish(request, db, user, browser, device):
    user.last_seen = datetime.now(timezone.utc).isoformat(timespec="seconds")
    response = after_login_redirect(request, "/teacher" if user.role == "teacher" else "/projects")
    set_session_cookie(response, user, request, db, device=device, browser_token=browser)
    response.delete_cookie(PENDING_COOKIE)
    return response


def _new_device(db, user, browser, label):
    now = int(time.time())
    device = AccountDevice(id=secrets.token_urlsafe(24), user_id=user.id,
        browser_hash=secret_hash(browser), label=label, verified_at=now, last_used_at=now)
    db.add(device)
    return device


def begin_login(request, db, user, *, email_just_verified=False):
    expected_version = user.session_version
    user = lock_account(db, user.id)
    if not user or user.session_version != expected_version:
        raise HTTPException(401, "Tài khoản vừa thay đổi. Hãy đăng nhập lại.")
    if user.role != "teacher" and not is_admin(user):
        raise HTTPException(403, "Tài khoản không có quyền truy cập hệ thống")
    browser = browser_secret(request) or secrets.token_urlsafe(32)
    known = db.scalar(select(AccountDevice).where(
        AccountDevice.user_id == user.id, AccountDevice.browser_hash == secret_hash(browser)))
    if known:
        return _finish(request, db, user, browser, known)
    # Registration has just proved this email in the same CSRF-bound browser.
    if email_just_verified and not device_rows(db, user.id):
        return _finish(request, db, user, browser, _new_device(db, user, browser, device_label(request)))
    if (rate_limit_exceeded("device_login_account", str(user.id), limit=5, window_seconds=900)
            or rate_limit_exceeded("device_login_ip", client_rate_limit_key(request), limit=15, window_seconds=900)):
        raise HTTPException(429, "Bạn đã yêu cầu xác minh quá nhiều lần. Hãy thử lại sau 15 phút.")
    now = int(time.time())
    db.execute(delete(DeviceLoginChallenge).where(
        DeviceLoginChallenge.user_id == user.id, DeviceLoginChallenge.expires_at <= now))
    db.execute(delete(DeviceLoginChallenge).where(
        DeviceLoginChallenge.user_id == user.id, DeviceLoginChallenge.browser_hash == secret_hash(browser)))
    token = secrets.token_urlsafe(32)
    otp = f"{secrets.randbelow(1_000_000):06d}"
    challenge = DeviceLoginChallenge(token_hash=secret_hash(token), user_id=user.id,
        browser_hash=secret_hash(browser), session_version=user.session_version,
        otp_hash=otp_digest(secret_hash(token), otp), label=device_label(request),
        expires_at=now + CHALLENGE_TTL, attempts=0, verified=False)
    db.add(challenge)
    db.commit()
    try:
        sent = send_device_login_otp_email(user.email, otp, challenge.label)
    except (OSError, smtplib.SMTPException, RuntimeError, ValueError):
        sent = False
    if not sent:
        db.delete(challenge)
        db.commit()
        raise HTTPException(503, "Chưa gửi được mã xác minh thiết bị. Hãy kiểm tra dịch vụ email rồi thử lại.")
    response = RedirectResponse("/auth/device", 303, headers={"Cache-Control": "no-store"})
    response.set_cookie(PENDING_COOKIE, token, max_age=CHALLENGE_TTL,
                        httponly=True, secure=secure_cookies(), samesite="lax")
    response.set_cookie(DEVICE_COOKIE, browser, max_age=DEVICE_COOKIE_TTL,
                        httponly=True, secure=secure_cookies(), samesite="lax")
    return response


def pending_login_candidate(request, db):
    token = request.cookies.get(PENDING_COOKIE, "")
    browser = browser_secret(request)
    if not browser or not isinstance(token, str) or len(token) != 43:
        return None
    row = db.get(DeviceLoginChallenge, secret_hash(token))
    return row if row and hmac.compare_digest(row.browser_hash, secret_hash(browser)) else None


def cancel_pending_login(request, db):
    initial = pending_login_candidate(request, db)
    if initial is None:
        return
    lock_account(db, initial.user_id)
    row = db.scalar(select(DeviceLoginChallenge).where(
        DeviceLoginChallenge.token_hash == initial.token_hash).with_for_update()
        .execution_options(populate_existing=True))
    if row and hmac.compare_digest(row.browser_hash, secret_hash(browser_secret(request))):
        db.delete(row)
        db.flush()


def pending_login(request, db):
    token = request.cookies.get(PENDING_COOKIE, "")
    browser = browser_secret(request)
    if not browser or not isinstance(token, str) or len(token) != 43:
        raise HTTPException(401, "Phiên xác minh đã hết hạn. Hãy đăng nhập lại.")
    initial = db.get(DeviceLoginChallenge, secret_hash(token))
    if initial is None:
        raise HTTPException(401, "Phiên xác minh đã hết hạn. Hãy đăng nhập lại.")
    # Every admission locks the account first, then its one-use challenge.
    user = lock_account(db, initial.user_id)
    challenge = db.scalar(select(DeviceLoginChallenge).where(
        DeviceLoginChallenge.token_hash == secret_hash(token)).with_for_update()
        .execution_options(populate_existing=True))
    if (not user or not challenge or challenge.expires_at <= int(time.time())
            or challenge.session_version != user.session_version
            or not hmac.compare_digest(challenge.browser_hash, secret_hash(browser))):
        raise HTTPException(401, "Phiên xác minh đã hết hạn. Hãy đăng nhập lại.")
    return user, challenge, browser


def complete_login(request, db, user, challenge, browser, replace_id=None):
    if not challenge.verified:
        raise HTTPException(403, "Hãy xác minh mã OTP trước")
    devices = device_rows(db, user.id)
    known = next((row for row in devices if row.browser_hash == secret_hash(browser)), None)
    if not known and len(devices) >= MAX_DEVICES:
        selected = next((row for row in devices if row.id == replace_id), None)
        if not selected:
            return challenge_page(request, db, user, challenge,
                error="Chọn một thiết bị để đăng xuất trước khi thêm thiết bị này." if replace_id else None)
        db.delete(selected)
        db.flush()
    device = known or _new_device(db, user, browser, challenge.label)
    db.delete(challenge)
    return _finish(request, db, user, browser, device)
