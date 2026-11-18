"""Browser-bound form tokens, including the unauthenticated login form."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException
from starlette.requests import HTTPConnection
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import SECRET_KEY
from app.settings import APP_BASE_URL, APP_ENV

CSRF_COOKIE = "auth_form_browser"
CSRF_TTL = 24 * 60 * 60
_token = re.compile(r"[A-Za-z0-9_-]{43}")
_signer = URLSafeTimedSerializer(SECRET_KEY, salt="browser-form-csrf-v1")


class FormSecurityError(HTTPException):
    """A rejected browser form is not an account authorization failure."""

    def __init__(self, message: str, code: str):
        super().__init__(403, message)
        self.code = code


def secure_cookies() -> bool:
    return APP_ENV == "production" or APP_BASE_URL.lower().startswith("https://")


def form_token(request):
    nonce = request.cookies.get(CSRF_COOKIE, "")
    if not _token.fullmatch(nonce):
        nonce = secrets.token_urlsafe(32)
    return nonce, _signer.dumps(hashlib.sha256(nonce.encode()).hexdigest())


def require_same_origin(request, *, allow_missing=True):
    origin = request.headers.get("origin")
    if not origin:
        if allow_missing and request.headers.get("sec-fetch-site") != "cross-site":
            return
        raise FormSecurityError("Vui lòng mở lại trang Smart TKB rồi thử lại.", "invalid_origin")
    try:
        supplied = urlsplit(origin)
        fallback = str(request.base_url).replace("wss://", "https://", 1).replace("ws://", "http://", 1)
        allowed = urlsplit(APP_BASE_URL or fallback)
        def normalized(parts):
            scheme = parts.scheme.lower()
            if scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
                raise ValueError
            return scheme, parts.hostname.lower(), parts.port or (443 if scheme == "https" else 80)
        if normalized(supplied) != normalized(allowed):
            raise ValueError
        if supplied.path not in {"", "/"} or supplied.query or supplied.fragment:
            raise ValueError
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise ValueError
    except (TypeError, ValueError):
        raise FormSecurityError("Vui lòng mở lại trang Smart TKB rồi thử lại.", "invalid_origin") from None


def require_form_token(request, token: str):
    nonce = request.cookies.get(CSRF_COOKIE, "")
    try:
        expected = _signer.loads(token, max_age=CSRF_TTL)
        if not _token.fullmatch(nonce) or not isinstance(expected, str):
            raise ValueError
        if not hmac.compare_digest(expected, hashlib.sha256(nonce.encode()).hexdigest()):
            raise ValueError
        require_same_origin(request)
    except (BadSignature, TypeError, ValueError):
        raise FormSecurityError("Trang đã mở quá lâu hoặc thông tin chưa đầy đủ. Vui lòng tải lại rồi thử lại.",
                                "expired_form") from None


async def verify_request_csrf(request: HTTPConnection):
    """FastAPI dependency for every HTTP mutation, including JSON and uploads."""
    if request.scope["type"] != "http" or request.scope.get("method", "GET").upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    token = request.headers.get("x-csrf-token", "")
    if not token:
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type in {"application/x-www-form-urlencoded", "multipart/form-data"}:
            form = await request.form()
            value = form.get("csrf_token", "")
            token = value if isinstance(value, str) else ""
    require_form_token(request, token)
