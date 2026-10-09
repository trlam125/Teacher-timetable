from __future__ import annotations

from app.models import User
from app.services.authentication.credentials import pwd, signer
from app.services.authentication.permissions import is_admin
from app.services.authentication.rate_limits import (
    clear_rate_limit_bucket,
    client_rate_limit_key,
    rate_limit_blocked,
    rate_limit_exceeded,
)
from app.services.authentication.sessions import db_session, set_session_cookie
from app.services.realtime.utils import _utc_now_iso
from app.services.web import templates
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired
from sqlalchemy import select
from sqlalchemy.orm import Session


router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    error = None
    notice = request.cookies.get("oauth_notice")
    if notice:
        try:
            error = signer.loads(notice, max_age=60).get("message")
        except (BadSignature, SignatureExpired, AttributeError):
            pass
    response = templates.TemplateResponse(
        "auth.html", {"request": request, "mode": "login", "error": error}
    )
    if notice:
        response.delete_cookie("oauth_notice")
    response.headers["Cache-Control"] = "no-store"
    return response



@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(db_session),
):
    normalized_email = email.lower().strip()
    ip_key = client_rate_limit_key(request)
    if rate_limit_blocked(
        "login_ip", ip_key, limit=20, window_seconds=10 * 60
    ) or rate_limit_blocked(
        "login_email", normalized_email, limit=8, window_seconds=10 * 60
    ):
        return templates.TemplateResponse(
            "auth.html",
            {
                "request": request,
                "mode": "login",
                "error": "Bạn đã thử đăng nhập sai quá nhiều lần. Vui lòng đợi vài phút rồi thử lại.",
            },
            status_code=429,
        )
    user = db.scalar(select(User).where(User.email == normalized_email))
    if not user or not pwd.verify(password, user.password_hash):
        ip_limited = rate_limit_exceeded(
            "login_ip", ip_key, limit=20, window_seconds=10 * 60
        )
        email_limited = rate_limit_exceeded(
            "login_email", normalized_email, limit=8, window_seconds=10 * 60
        )
        if ip_limited or email_limited:
            return templates.TemplateResponse(
                "auth.html",
                {
                    "request": request,
                    "mode": "login",
                    "error": "Bạn đã thử đăng nhập sai quá nhiều lần. Vui lòng đợi vài phút rồi thử lại.",
                },
                status_code=429,
            )
        return templates.TemplateResponse(
            "auth.html",
            {
                "request": request,
                "mode": "login",
                "error": "Email hoặc mật khẩu không đúng",
            },
            status_code=400,
        )
    # Chỉ lỗi đăng nhập mới được tính vào rate-limit. Đăng nhập đúng xóa bucket
    # theo email để các lần đăng nhập hợp lệ không tự khóa tài khoản.
    clear_rate_limit_bucket("login_email", normalized_email)
    destination = (
        "/teacher"
        if user.role == "teacher"
        else ("/projects" if is_admin(user) else "/logout")
    )
    user.last_seen = _utc_now_iso()
    db.commit()
    res = RedirectResponse(destination, 303)
    set_session_cookie(res, user)
    return res
