from __future__ import annotations

from fastapi import APIRouter
from app.services.runtime import *

router = APIRouter()

@router.get("/api/server-time")
def server_time():
    """Return authoritative server time for the shared app-bar clock."""
    return JSONResponse(
        {
            "epoch_ms": time.time_ns() // 1_000_000,
            "timezone": "Asia/Ho_Chi_Minh",
            "utc_offset": "+07:00",
        },
        headers={"Cache-Control": "no-store, max-age=0"},
    )

@router.get("/api/mobile/config")
def mobile_config():
    # Legacy endpoint kept for backward compatibility. The V1 APK discovers the backend
    # through Firebase Hosting config.json and does not depend on this endpoint.
    return JSONResponse(
        {"apk_base_url": APP_BASE_URL},
        headers={"Cache-Control": "no-store, max-age=0"},
    )

