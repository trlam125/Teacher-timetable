"""Return to a shared timetable after signing in, without external redirects."""
from __future__ import annotations

import re

from fastapi import Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import SECRET_KEY
from app.settings import APP_BASE_URL, APP_ENV

SHARE_RETURN_COOKIE = "share_login_return"
SHARE_RETURN_TTL = 15 * 60
_share_path = re.compile(r"/share/[A-Za-z0-9_-]{1,64}")
_signer = URLSafeTimedSerializer(SECRET_KEY, salt="share-login-return-v1")


def login_redirect(request: Request) -> RedirectResponse:
    response = RedirectResponse("/login", 303, headers={"Cache-Control": "no-store"})
    path = request.url.path
    if _share_path.fullmatch(path):
        response.set_cookie(
            SHARE_RETURN_COOKIE, _signer.dumps({"path": path}), max_age=SHARE_RETURN_TTL,
            httponly=True, secure=APP_ENV == "production" or APP_BASE_URL.lower().startswith("https://"),
            samesite="lax",
        )
    return response


def after_login_redirect(request: Request, fallback: str) -> RedirectResponse:
    destination = fallback
    raw = request.cookies.get(SHARE_RETURN_COOKIE)
    if raw and fallback != "/logout":
        try:
            path = _signer.loads(raw, max_age=SHARE_RETURN_TTL).get("path")
            if isinstance(path, str) and _share_path.fullmatch(path):
                destination = path
        except (BadSignature, AttributeError):
            pass
    response = RedirectResponse(destination, 303, headers={"Cache-Control": "no-store"})
    if raw:
        response.delete_cookie(SHARE_RETURN_COOKIE)
    return response
