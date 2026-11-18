"""Remember browsers, limit live sessions and notify about new-device logins."""
from __future__ import annotations

from datetime import datetime, timezone
import hmac
import secrets
import smtplib
import time

from fastapi import HTTPException
from sqlalchemy import delete, select
from starlette.background import BackgroundTask

from app.logging_config import logger
from app.models import AccountDevice, DeviceLoginChallenge
from app.services.authentication.mail import send_device_login_alert_email
from app.services.authentication.navigation import after_login_redirect
from app.services.authentication.permissions import is_admin
from app.services.authentication.sessions import (
    MAX_ACTIVE_DEVICES, browser_secret, lock_account, secret_hash, set_session_cookie,
)

PENDING_COOKIE = "device_login"


def device_label(request):
    ua = request.headers.get("user-agent", "")[:1024]
    browser = next((name for marker, name in (("Edg", "Edge"), ("OPR/", "Opera"),
        ("Firefox/", "Firefox"), ("FxiOS/", "Firefox"), ("Chrome/", "Chrome"),
        ("CriOS/", "Chrome"), ("Safari/", "Safari")) if marker in ua), "Trình duyệt")
    platform = next((name for marker, name in (("Android", "Android"), ("iPhone", "iPhone"),
        ("iPad", "iPad"), ("Windows", "Windows"), ("Macintosh", "macOS"),
        ("Linux", "Linux")) if marker in ua), "Thiết bị khác")
    return f"{browser} trên {platform}"


def _send_login_alert(recipient, label, logged_in_at):
    # Mail outages must never lock out a successfully committed login.
    try:
        if not send_device_login_alert_email(recipient, label, logged_in_at):
            logger.warning("New-device login alert could not be delivered")
    except (OSError, smtplib.SMTPException, RuntimeError, ValueError):
        logger.warning("New-device login alert delivery failed")


def begin_login(request, db, user, *, email_just_verified=False):
    expected_version = user.session_version
    user = lock_account(db, user.id)
    if not user or user.session_version != expected_version:
        raise HTTPException(401, "Tài khoản vừa thay đổi. Hãy đăng nhập lại.")
    if user.role != "teacher" and not is_admin(user):
        raise HTTPException(403, "Tài khoản không có quyền truy cập hệ thống")

    browser = browser_secret(request) or secrets.token_urlsafe(32)
    device = db.scalar(select(AccountDevice).where(
        AccountDevice.user_id == user.id, AccountDevice.browser_hash == secret_hash(browser)))
    is_new = device is None
    now = int(time.time())
    label = device_label(request)
    if is_new:
        device = AccountDevice(id=secrets.token_urlsafe(24), user_id=user.id,
            browser_hash=secret_hash(browser), label=label, verified_at=now, last_used_at=now)
        db.add(device)
    else:
        device.label = label

    # Account-row lock serializes admissions, including concurrent new logins.
    # Remembered, logged-out and expired browsers do not occupy a live slot.
    active = db.scalars(select(AccountDevice).where(
        AccountDevice.user_id == user.id, AccountDevice.id != device.id,
        AccountDevice.session_hash.is_not(None), AccountDevice.session_expires_at > now,
    ).order_by(AccountDevice.last_used_at.desc(), AccountDevice.id)).all()
    for previous in active[MAX_ACTIVE_DEVICES - 1:]:
        previous.session_hash = None
        previous.session_expires_at = 0

    db.execute(delete(DeviceLoginChallenge).where(DeviceLoginChallenge.user_id == user.id))
    user.last_seen = datetime.now(timezone.utc).isoformat(timespec="seconds")
    response = after_login_redirect(request, "/teacher" if user.role == "teacher" else "/projects")
    set_session_cookie(response, user, request, db, device=device, browser_token=browser)
    response.delete_cookie(PENDING_COOKIE)
    if is_new and not email_just_verified:
        response.background = BackgroundTask(_send_login_alert, user.email, label,
                                              datetime.now(timezone.utc))
    return response


def pending_login_candidate(request, db):
    """Recognize legacy pending cookies only so logout can revoke them."""
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
