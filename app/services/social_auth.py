"""Provider configuration and server-side identity verification.

No access/refresh tokens are persisted or exposed to the browser.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import time
from urllib.parse import urlencode, urlsplit

import httpx
import jwt

from app.services.foundation import APP_BASE_URL, APP_ENV

PROVIDER_NAMES = {"google": "Google", "facebook": "Facebook"}
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
    prefix = "GOOGLE" if provider == "google" else "FACEBOOK"
    id_key = "CLIENT_ID" if provider == "google" else "APP_ID"
    secret_key = "CLIENT_SECRET" if provider == "google" else "APP_SECRET"
    client_id = os.getenv(f"{prefix}_{id_key}", "").strip()
    client_secret = os.getenv(f"{prefix}_{secret_key}", "").strip()
    if not client_id or not client_secret:
        raise SocialAuthError(f"Đăng nhập {PROVIDER_NAMES[provider]} chưa được cấu hình. Vui lòng liên hệ quản trị viên.")
    version = os.getenv("FACEBOOK_GRAPH_VERSION", "").strip()
    if provider == "facebook" and not re.fullmatch(r"v\d+\.\d+", version):
        raise SocialAuthError("Đăng nhập Facebook chưa được cấu hình đầy đủ. Vui lòng liên hệ quản trị viên.")
    return {"client_id": client_id, "client_secret": client_secret,
            "redirect_uri": f"{base}/auth/{provider}/callback", "version": version}


def authorization_url(provider: str, config: dict, state: str, nonce: str, verifier: str) -> str:
    params = {"client_id": config["client_id"], "redirect_uri": config["redirect_uri"],
              "response_type": "code", "state": state}
    if provider == "google":
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        params.update(scope="openid email profile", nonce=nonce, prompt="select_account",
                      code_challenge=challenge, code_challenge_method="S256")
        endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
    else:
        params.update(scope="email,public_profile", auth_type="rerequest")
        endpoint = f"https://www.facebook.com/{config['version']}/dialog/oauth"
    return endpoint + "?" + urlencode(params)


def _json(response: httpx.Response) -> dict:
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict) or "error" in result:
        raise SocialAuthError("Nhà cung cấp không thể xác thực tài khoản. Vui lòng thử lại.")
    return result


def exchange_identity(provider: str, config: dict, code: str, payload: dict) -> dict:
    """Verify Google's signed ID token or Facebook's app-bound access token."""
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            data = {"client_id": config["client_id"], "client_secret": config["client_secret"],
                    "redirect_uri": config["redirect_uri"], "code": code}
            if provider == "google":
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
            else:
                graph = f"https://graph.facebook.com/{config['version']}"
                token = _json(client.post(graph + "/oauth/access_token", data=data))
                access = token["access_token"]
                if not isinstance(access, str) or not access:
                    raise SocialAuthError("Không nhận được token xác thực Facebook hợp lệ.")
                debug = _json(client.get(graph + "/debug_token", params={"input_token": access},
                                        headers={"Authorization": f"Bearer {config['client_id']}|{config['client_secret']}"}))["data"]
                if (not isinstance(debug, dict) or debug.get("is_valid") is not True or str(debug.get("app_id")) != config["client_id"]
                        or not debug.get("user_id") or int(debug.get("expires_at", 0)) <= int(time.time())):
                    raise SocialAuthError("Phiên xác thực Facebook không hợp lệ. Vui lòng bắt đầu lại.")
                data_expiry = int(debug.get("data_access_expires_at", 0))
                if data_expiry and data_expiry <= int(time.time()):
                    raise SocialAuthError("Quyền truy cập Facebook đã hết hạn. Vui lòng cấp quyền lại.")
                proof = hmac.new(config["client_secret"].encode(), access.encode(), hashlib.sha256).hexdigest()
                profile = _json(client.get(graph + "/me", params={"fields": "id,name,email", "appsecret_proof": proof},
                                           headers={"Authorization": f"Bearer {access}"}))
                if str(profile.get("id")) != str(debug["user_id"]):
                    raise SocialAuthError("Không thể xác minh tài khoản Facebook.")
                identity = {"subject": str(profile["id"]), "name": profile.get("name", ""),
                            "email": profile.get("email", "")}
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
