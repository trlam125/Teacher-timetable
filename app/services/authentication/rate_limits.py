from __future__ import annotations

import hashlib
import hmac
import secrets
from app.config import SECRET_KEY
from app.database import engine
from datetime import datetime, timezone
from fastapi import Request


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
