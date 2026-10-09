from __future__ import annotations

from app.database import SessionLocal
from app.models import User
from app.services.authentication.credentials import signer
from app.services.foundation import APP_BASE_URL, APP_ENV, SESSION_TTL_SECONDS
from app.services.web import _parse_iso_datetime
from datetime import datetime, timezone
from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired
from sqlalchemy.orm import Session


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


def set_session_cookie(response, user: User):
    response.set_cookie(
        "session",
        signer.dumps({"uid": user.id, "sv": user.session_version}),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=APP_ENV == "production" or APP_BASE_URL.lower().startswith("https://"),
    )


def current_user(request: Request, db: Session = Depends(db_session)) -> User:
    raw = request.cookies.get("session")
    if not raw:
        raise HTTPException(401)
    try:
        data = signer.loads(raw, max_age=SESSION_TTL_SECONDS)
        user = db.get(User, int(data["uid"]))
        if not user or int(data.get("sv", -1)) != user.session_version:
            raise HTTPException(401)
        now = datetime.now(timezone.utc)
        previous = _parse_iso_datetime(user.last_seen)
        if previous is None or (now - previous).total_seconds() >= 60:
            user.last_seen = now.isoformat(timespec="seconds")
            db.commit()
        return user
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        raise HTTPException(401)


def development_reset_links_enabled(request: Request) -> bool:
    host = (request.url.hostname or "").lower()
    return APP_ENV == "development" and host in {"localhost", "127.0.0.1", "::1"}
