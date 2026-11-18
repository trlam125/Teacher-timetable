from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import re
import secrets
import time

from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import AccountDevice, User
from app.services.authentication.csrf import secure_cookies
from app.services.authentication.credentials import signer
from app.services.web import _parse_iso_datetime
from app.settings import APP_BASE_URL, APP_ENV, SESSION_TTL_SECONDS


def public_base_url(request: Request) -> str | None:
    if APP_BASE_URL:
        return APP_BASE_URL
    if development_reset_links_enabled(request):
        return str(request.base_url).rstrip("/")
    return None


def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DEVICE_COOKIE = "trusted_browser"
DEVICE_COOKIE_TTL = 365 * 24 * 60 * 60
_secret = re.compile(r"[A-Za-z0-9_-]{43}")


def secret_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def browser_secret(request) -> str | None:
    value = request.cookies.get(DEVICE_COOKIE, "")
    return value if _secret.fullmatch(value) else None


def lock_account(db: Session, user_id: int) -> User | None:
    return db.scalar(select(User).where(User.id == user_id).with_for_update()
                     .execution_options(populate_existing=True, autoflush=False))


def invalidate_credential_state(user: User):
    user.session_version += 1
    user.reset_token_hash = None
    user.reset_token_expires_at = None


def set_session_cookie(response, user: User, request, db: Session, *, device=None, browser_token=None):
    browser_token = browser_token or browser_secret(request)
    if not browser_token:
        raise HTTPException(401, "Thiết bị chưa được xác minh")
    if device is None:
        device = db.scalar(select(AccountDevice).where(
            AccountDevice.user_id == user.id,
            AccountDevice.browser_hash == secret_hash(browser_token)))
    if not device or device.user_id != user.id or device.browser_hash != secret_hash(browser_token):
        raise HTTPException(401, "Thiết bị chưa được xác minh")
    session_secret = secrets.token_urlsafe(32)
    device.session_hash = secret_hash(session_secret)
    device.last_used_at = int(time.time())
    device.session_expires_at = int(time.time()) + SESSION_TTL_SECONDS
    db.commit()
    response.set_cookie(
        "session",
        signer.dumps({"uid": user.id, "sv": user.session_version,
                      "did": device.id, "sid": session_secret}),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=secure_cookies(),
    )
    response.set_cookie(DEVICE_COOKIE, browser_token, max_age=DEVICE_COOKIE_TTL,
                        httponly=True, samesite="lax", secure=secure_cookies())


def session_user(cookies, db: Session) -> User | None:
    """One validation path for HTTP, home redirects and every WebSocket event."""
    try:
        data = signer.loads(cookies.get("session", ""), max_age=SESSION_TTL_SECONDS)
        browser = cookies.get(DEVICE_COOKIE, "")
        sid = data.get("sid", "")
        if not _secret.fullmatch(browser) or not isinstance(sid, str) or not _secret.fullmatch(sid):
            return None
        user = db.get(User, int(data["uid"]))
        device = db.get(AccountDevice, str(data["did"]))
        if (not user or int(data.get("sv", -1)) != user.session_version
                or not device or device.user_id != user.id
                or device.session_expires_at <= int(time.time())
                or not device.session_hash
                or not hmac.compare_digest(device.browser_hash, secret_hash(browser))
                or not hmac.compare_digest(device.session_hash, secret_hash(sid))):
            return None
        return user
    except (BadSignature, KeyError, TypeError, ValueError, AttributeError):
        return None


def require_live_session(request, db: Session) -> User:
    """Recheck after taking the account lock, before any sensitive mutation."""
    db.expire_all()
    user = session_user(request.cookies, db)
    if user is None:
        raise HTTPException(401)
    return user


def current_user(request: Request, db: Session = Depends(db_session)) -> User:
    user = session_user(request.cookies, db)
    if not user:
        raise HTTPException(401)
    now = datetime.now(timezone.utc)
    previous = _parse_iso_datetime(user.last_seen)
    device = db.scalar(select(AccountDevice).where(AccountDevice.user_id == user.id,
        AccountDevice.browser_hash == secret_hash(browser_secret(request))))
    changed = False
    if device and int(now.timestamp()) - device.last_used_at >= 60:
        device.last_used_at = int(now.timestamp())
        changed = True
    if previous is None or (now - previous).total_seconds() >= 60:
        user.last_seen = now.isoformat(timespec="seconds")
        changed = True
    if changed:
        db.commit()
    return user


def development_reset_links_enabled(request: Request) -> bool:
    host = (request.url.hostname or "").lower()
    return APP_ENV == "development" and host in {"localhost", "127.0.0.1", "::1"}
