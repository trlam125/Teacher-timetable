from __future__ import annotations

import json
import secrets
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import OAuthAttempt, RegistrationVerification, SocialIdentity, User
from app.services.auth import (
    clear_rate_limit_bucket, client_rate_limit_key, db_session, is_admin, pwd,
    rate_limit_blocked, rate_limit_exceeded,
    set_session_cookie,
)
from app.services.foundation import APP_BASE_URL, APP_ENV
from app.services.social_auth import (
    PROVIDER_NAMES, SocialAuthError, authorization_url, digest, exchange_identity,
    provider_config,
)
from app.services.web import templates

router = APIRouter()
TTL = 600
COOKIE = "oauth_browser"
LINK_COOKIE = "oauth_link"
COOKIE_PATH = "/auth"


def private_response(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def cookie(response, name, value):
    response.set_cookie(name, value, max_age=TTL, path=COOKIE_PATH, httponly=True,
                        secure=APP_ENV == "production" or APP_BASE_URL.startswith("https://"), samesite="lax")


def clear_cookies(response):
    for name in (COOKIE, LINK_COOKIE):
        response.delete_cookie(name, path=COOKIE_PATH)
    return private_response(response)


def failure(request, message):
    # Render at /login after redirect so the password form posts to /login.
    # Only fixed application messages are signed into the short-lived notice cookie.
    from app.services.auth import signer
    response = RedirectResponse("/login", 303)
    response.set_cookie("oauth_notice", signer.dumps({"message": message}), max_age=60,
                        httponly=True, secure=APP_ENV == "production" or APP_BASE_URL.startswith("https://"), samesite="lax")
    return clear_cookies(response)


def finish(db, user):
    if user.role != "teacher" and not is_admin(user):
        raise SocialAuthError("Tài khoản không có quyền truy cập hệ thống.")
    user.last_seen = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.commit()
    response = RedirectResponse("/teacher" if user.role == "teacher" else "/projects", 303)
    set_session_cookie(response, user)
    return clear_cookies(response)


def find_identity(db, provider, subject):
    return db.scalar(select(SocialIdentity).where(
        SocialIdentity.provider == provider, SocialIdentity.subject == subject))


@router.get("/auth/{provider}/login")
def social_login(provider: str, request: Request, db: Session = Depends(db_session)):
    try:
        config = provider_config(provider)
        if rate_limit_exceeded("oauth_start", client_rate_limit_key(request), limit=30, window_seconds=600):
            raise SocialAuthError("Bạn đã thử đăng nhập quá nhiều lần. Vui lòng đợi vài phút.")
        # OAuth must begin on the configured origin, where the browser cookie lives.
        # Behind a proxy request.url may be HTTP; the host still must match.
        from urllib.parse import urlsplit
        expected = urlsplit(APP_BASE_URL).netloc.lower()
        if request.url.netloc.lower() != expected:
            return private_response(RedirectResponse(f"{APP_BASE_URL}/auth/{provider}/login", 303))
        state, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        now = int(time.time())
        db.execute(delete(OAuthAttempt).where(OAuthAttempt.expires_at <= now))
        db.add(OAuthAttempt(state_hash=digest(state), browser_hash=digest(browser), provider=provider,
                            phase="authorize", expires_at=now + TTL,
                            payload_json=json.dumps({"nonce": nonce, "verifier": verifier,
                                                     "redirect_uri": config["redirect_uri"]})))
        db.commit()
        response = RedirectResponse(authorization_url(provider, config, state, nonce, verifier), 303)
        cookie(response, COOKIE, browser)
        response.delete_cookie(LINK_COOKIE, path=COOKIE_PATH)
        return private_response(response)
    except SocialAuthError as exc:
        return failure(request, str(exc))


@router.get("/auth/{provider}/callback")
def social_callback(provider: str, request: Request, db: Session = Depends(db_session)):
    try:
        config = provider_config(provider)
        state = request.query_params.get("state", "")
        browser = request.cookies.get(COOKIE, "")
        if not state or len(state) > 200 or not browser or len(browser) > 200:
            raise SocialAuthError("Phiên đăng nhập đã hết hạn hoặc không hợp lệ. Hãy bắt đầu lại.")
        # Atomic DELETE RETURNING consumes state across workers and concurrent callbacks.
        payload_json = db.execute(delete(OAuthAttempt).where(
            OAuthAttempt.state_hash == digest(state), OAuthAttempt.browser_hash == digest(browser),
            OAuthAttempt.provider == provider, OAuthAttempt.phase == "authorize",
            OAuthAttempt.expires_at > int(time.time())).returning(OAuthAttempt.payload_json)).scalar_one_or_none()
        db.commit()
        if payload_json is None:
            raise SocialAuthError("Phiên đăng nhập đã hết hạn hoặc đã được sử dụng. Hãy bắt đầu lại.")
        if request.query_params.get("error"):
            raise SocialAuthError("Bạn đã hủy hoặc chưa cấp quyền đăng nhập. Bạn có thể thử lại.")
        code = request.query_params.get("code", "")
        if not code or len(code) > 8192:
            raise SocialAuthError("Không nhận được mã xác thực. Hãy thử đăng nhập lại.")
        payload = json.loads(payload_json)
        if payload["redirect_uri"] != config["redirect_uri"]:
            raise SocialAuthError("Địa chỉ đăng nhập đã thay đổi. Hãy bắt đầu lại.")
        identity = exchange_identity(provider, config, code, payload)
        linked = find_identity(db, provider, identity["subject"])
        if linked:
            user = db.get(User, linked.user_id)
            if not user:
                raise SocialAuthError("Tài khoản không còn tồn tại.")
            return finish(db, user)
        if not identity["email"]:
            raise SocialAuthError("Cần email để tạo hoặc liên kết tài khoản. Hãy cho phép chia sẻ email đã xác minh, dùng Google hoặc đăng ký bằng email.")
        user = db.scalar(select(User).where(func.lower(User.email) == identity["email"]))
        if user:
            token = secrets.token_urlsafe(32)
            db.add(OAuthAttempt(state_hash=digest(token), browser_hash=digest(browser), provider=provider,
                                phase="link", expires_at=int(time.time()) + TTL,
                                payload_json=json.dumps({"user_id": user.id, "session_version": user.session_version,
                                                         **identity})))
            db.commit()
            response = RedirectResponse("/auth/social/link", 303)
            cookie(response, LINK_COOKIE, token)
            cookie(response, COOKIE, browser)
            return private_response(response)
        # New social users never inherit admin rights and have no usable password.
        user = User(email=identity["email"], name=identity["name"], password_hash="!social-login-only",
                    role="teacher", is_superadmin=False)
        db.add(user)
        db.flush()
        db.add(SocialIdentity(user_id=user.id, provider=provider, subject=identity["subject"]))
        db.execute(delete(RegistrationVerification).where(RegistrationVerification.email == identity["email"]))
        return finish(db, user)
    except IntegrityError:
        db.rollback()
        return failure(request, "Tài khoản vừa được cập nhật ở phiên khác. Vui lòng đăng nhập lại.")
    except SocialAuthError as exc:
        db.rollback()
        return failure(request, str(exc))


def pending_link(request, db, *, lock=False):
    token, browser = request.cookies.get(LINK_COOKIE, ""), request.cookies.get(COOKIE, "")
    if not token or not browser or len(token) > 200 or len(browser) > 200:
        raise SocialAuthError("Yêu cầu liên kết đã hết hạn. Hãy đăng nhập lại bằng Google hoặc Facebook.")
    query = select(OAuthAttempt).where(OAuthAttempt.state_hash == digest(token),
        OAuthAttempt.browser_hash == digest(browser), OAuthAttempt.phase == "link",
        OAuthAttempt.expires_at > int(time.time()))
    attempt = db.scalar(query.with_for_update() if lock else query)
    if not attempt:
        raise SocialAuthError("Yêu cầu liên kết đã hết hạn. Hãy bắt đầu lại.")
    payload = json.loads(attempt.payload_json)
    user_query = select(User).where(User.id == payload["user_id"])
    user = db.scalar(user_query.with_for_update() if lock else user_query)
    if not user or user.email.lower() != payload["email"] or user.session_version != payload["session_version"]:
        raise SocialAuthError("Tài khoản đã thay đổi. Hãy bắt đầu lại để xác thực.")
    return attempt, payload, user, token


def link_page(request, attempt, user, token, error=None, status=200):
    return private_response(templates.TemplateResponse("social_link.html", {
        "request": request, "provider_name": PROVIDER_NAMES[attempt.provider],
        "email": user.email, "link_token": token, "error": error}, status_code=status))


@router.get("/auth/social/link")
def social_link_page(request: Request, db: Session = Depends(db_session)):
    try:
        attempt, payload, user, token = pending_link(request, db)
        return link_page(request, attempt, user, token)
    except SocialAuthError as exc:
        return failure(request, str(exc))


@router.post("/auth/social/link")
def social_link(request: Request, password: str = Form(...), link_token: str = Form(...),
                db: Session = Depends(db_session)):
    try:
        import hmac
        if (not link_token or len(link_token) > 200
                or not hmac.compare_digest(link_token.encode(), request.cookies.get(LINK_COOKIE, "").encode())):
            raise SocialAuthError("Yêu cầu xác nhận không hợp lệ. Hãy bắt đầu lại.")
        # Limit before locking: the limiter uses its own database transaction.
        if (rate_limit_exceeded("oauth_link_ip", client_rate_limit_key(request), limit=15, window_seconds=600)
                or rate_limit_exceeded("oauth_link_token", digest(link_token), limit=5, window_seconds=600)):
            raise SocialAuthError("Đã thử xác nhận quá nhiều lần. Vui lòng đợi vài phút rồi bắt đầu lại.")
        attempt, payload, user, token = pending_link(request, db, lock=True)
        if rate_limit_blocked("login_email", user.email, limit=8, window_seconds=600):
            raise SocialAuthError("Tài khoản đã thử sai mật khẩu quá nhiều lần. Vui lòng đợi vài phút.")
        if not pwd.verify(password, user.password_hash):
            rate_limit_exceeded("login_email", user.email, limit=8, window_seconds=600)
            return link_page(request, attempt, user, token, "Mật khẩu tài khoản Smart TKB không đúng.", 400)
        if find_identity(db, attempt.provider, payload["subject"]) or db.scalar(select(SocialIdentity).where(
                SocialIdentity.user_id == user.id, SocialIdentity.provider == attempt.provider)):
            raise SocialAuthError("Tài khoản đã có liên kết với nhà cung cấp này. Vui lòng đăng nhập lại.")
        db.add(SocialIdentity(user_id=user.id, provider=attempt.provider, subject=payload["subject"]))
        db.delete(attempt)
        clear_rate_limit_bucket("login_email", user.email)
        return finish(db, user)
    except IntegrityError:
        db.rollback()
        return failure(request, "Liên kết vừa thay đổi ở phiên khác. Vui lòng đăng nhập lại.")
    except SocialAuthError as exc:
        db.rollback()
        return failure(request, str(exc))
