from __future__ import annotations

import hashlib
import hmac
import secrets
from app.config import SECRET_KEY
from app.database import engine
from datetime import datetime, timezone
from fastapi import Request
from fastapi import HTTPException
from app.services.authentication.credentials import pwd


def verify_sensitive_password(request, account, password: str) -> bool:
    """Password confirmation must not become a second, less limited guessing API."""
    ip_key = client_rate_limit_key(request)
    if (rate_limit_blocked("login_email", account.email, limit=8, window_seconds=600)
            or rate_limit_blocked("login_ip", ip_key, limit=20, window_seconds=600)):
        raise HTTPException(429, "Bạn đã thử sai mật khẩu quá nhiều lần. Hãy thử lại sau 10 phút.")
    if not pwd.verify(password, account.password_hash):
        limited_email = rate_limit_exceeded("login_email", account.email, limit=8, window_seconds=600)
        limited_ip = rate_limit_exceeded("login_ip", ip_key, limit=20, window_seconds=600)
        if limited_email or limited_ip:
            raise HTTPException(429, "Bạn đã thử sai mật khẩu quá nhiều lần. Hãy thử lại sau 10 phút.")
        return False
    clear_rate_limit_bucket("login_email", account.email)
    return True


def _rate_limit_identity(value: str) -> str:
    return hmac.new(SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()[
        :48
    ]


def client_rate_limit_key(request: Request) -> str:
    host = request.client.host if request.client and request.client.host else "unknown"
    return _rate_limit_identity(host.strip().lower())


def rate_limit_exceeded(
    scope: str, identity: str, *, limit: int, window_seconds: int
) -> bool:
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    cutoff = now_epoch - window_seconds
    bucket_key = f"{scope}:{_rate_limit_identity(identity.strip().lower())}"
    with engine.begin() as connection:
        row = connection.exec_driver_sql(
            "INSERT INTO rate_limit_buckets (bucket_key, window_started_at, count, touched_at) "
            "VALUES (%s, %s, 1, %s) "
            "ON CONFLICT (bucket_key) DO UPDATE SET "
            "count=CASE WHEN rate_limit_buckets.window_started_at < %s THEN 1 ELSE rate_limit_buckets.count + 1 END, "
            "window_started_at=CASE WHEN rate_limit_buckets.window_started_at < %s THEN %s ELSE rate_limit_buckets.window_started_at END, "
            "touched_at=%s "
            "RETURNING count",
            (bucket_key, now_epoch, now_epoch, cutoff, cutoff, now_epoch, now_epoch),
        ).scalar_one()
        if secrets.randbelow(100) < 3:
            connection.exec_driver_sql(
                "DELETE FROM rate_limit_buckets WHERE touched_at < %s",
                (now_epoch - 24 * 60 * 60,),
            )
    return int(row) > limit


def rate_limit_blocked(
    scope: str, identity: str, *, limit: int, window_seconds: int
) -> bool:
    """Kiểm tra bucket hiện tại mà không tăng bộ đếm."""
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    cutoff = now_epoch - window_seconds
    bucket_key = f"{scope}:{_rate_limit_identity(identity.strip().lower())}"
    with engine.begin() as connection:
        row = (
            connection.exec_driver_sql(
                "SELECT window_started_at, count FROM rate_limit_buckets WHERE bucket_key=%s",
                (bucket_key,),
            )
            .mappings()
            .first()
        )
    if not row or int(row["window_started_at"]) < cutoff:
        return False
    return int(row["count"]) >= limit


def clear_rate_limit_bucket(scope: str, identity: str) -> None:
    bucket_key = f"{scope}:{_rate_limit_identity(identity.strip().lower())}"
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DELETE FROM rate_limit_buckets WHERE bucket_key=%s",
            (bucket_key,),
        )
