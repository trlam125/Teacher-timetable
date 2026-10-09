"""Provider configuration and server-side identity verification.

No access/refresh tokens are persisted or exposed to the browser.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from urllib.parse import urlencode, urlsplit

import httpx
import jwt

from app.services.foundation import APP_BASE_URL, APP_ENV

PROVIDER_NAMES = {"google": "Google"}
GOOGLE_KEYS = jwt.PyJWKClient("https://www.googleapis.com/oauth2/v3/certs", timeout=10)


class SocialAuthError(Exception):
    pass


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def provider_config(provider: str) -> dict:
    if provider not in PROVIDER_NAMES:
        raise SocialAuthError("Phương thức đăng nhập không được hỗ trợ.")
    base = APP_BASE_URL.rstrip("/")
    try:
        parsed = urlsplit(base)
        parsed.port  # Reject malformed ports before constructing a redirect.
    except ValueError:
        raise SocialAuthError("Địa chỉ website chưa được cấu hình hợp lệ. Vui lòng liên hệ quản trị viên.") from None
    local = APP_ENV == "development" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query
            or parsed.fragment or parsed.path or (parsed.scheme != "https" and not (local and parsed.scheme == "http"))):
        raise SocialAuthError("Đăng nhập mạng xã hội chưa được cấu hình. Vui lòng liên hệ quản trị viên.")
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise SocialAuthError("Đăng nhập Google chưa được cấu hình. Vui lòng liên hệ quản trị viên.")
    return {"client_id": client_id, "client_secret": client_secret,
            "redirect_uri": f"{base}/auth/google/callback"}


def authorization_url(provider: str, config: dict, state: str, nonce: str, verifier: str) -> str:
    params = {"client_id": config["client_id"], "redirect_uri": config["redirect_uri"],
              "response_type": "code", "state": state}
    if provider != "google":
        raise SocialAuthError("Phương thức đăng nhập không được hỗ trợ.")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params.update(scope="openid email profile", nonce=nonce, prompt="select_account",
                  code_challenge=challenge, code_challenge_method="S256")
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


def _json(response: httpx.Response) -> dict:
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict) or "error" in result:
        raise SocialAuthError("Nhà cung cấp không thể xác thực tài khoản. Vui lòng thử lại.")
    return result


def exchange_identity(provider: str, config: dict, code: str, payload: dict) -> dict:
    """Verify Google's signed ID token."""
    if provider != "google":
        raise SocialAuthError("Phương thức đăng nhập không được hỗ trợ.")
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            data = {"client_id": config["client_id"], "client_secret": config["client_secret"],
                    "redirect_uri": config["redirect_uri"], "code": code}
            data.update(grant_type="authorization_code", code_verifier=payload["verifier"])
            token = _json(client.post("https://oauth2.googleapis.com/token", data=data))
            raw = token["id_token"]
            key = GOOGLE_KEYS.get_signing_key_from_jwt(raw).key
            claims = jwt.decode(raw, key, algorithms=["RS256"], audience=config["client_id"],
                                issuer=["https://accounts.google.com", "accounts.google.com"],
                                options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]})
            if (not hmac.compare_digest(str(claims["nonce"]), payload["nonce"])
                    or claims.get("azp", config["client_id"]) != config["client_id"]):
                raise SocialAuthError("Phiên xác thực Google không hợp lệ. Vui lòng bắt đầu lại.")
            identity = {"subject": claims["sub"], "name": claims.get("name", ""),
                        "email": claims.get("email", "") if claims.get("email_verified") is True else ""}
        subject = identity["subject"]
        if not isinstance(subject, str) or not subject or len(subject) > 255:
            raise SocialAuthError("Nhà cung cấp trả về tài khoản không hợp lệ.")
        email = str(identity["email"] or "").strip().lower()
        identity["email"] = email if len(email) <= 255 and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) else ""
        identity["name"] = str(identity["name"] or "Giáo viên").strip()[:120] or "Giáo viên"
        return identity
    except SocialAuthError:
        raise
    except (httpx.HTTPError, jwt.PyJWTError, KeyError, ValueError, TypeError, OSError):
        # Never log exceptions containing provider URLs, codes or tokens.
        raise SocialAuthError("Chưa thể xác thực với nhà cung cấp. Vui lòng thử lại sau.") from None
