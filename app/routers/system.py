from __future__ import annotations

import time
import threading
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from app.settings import APP_BASE_URL
from app.services.traffic import TTLCache, TokenBuckets

router = APIRouter()


@router.api_route("/health", methods=["GET", "HEAD"], include_in_schema=False)
def health():
    return JSONResponse(
        {"status": "ok"},
        status_code=200,
        headers={"Cache-Control": "no-store"},
    )


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


_weather_cache = TTLCache(ttl=600, capacity=256)
_location_name_cache = TTLCache(ttl=86400, capacity=256)
_upstream_slots = threading.BoundedSemaphore(4)
_weather_requests = TokenBuckets(rate=2, burst=4, capacity=1)
_location_requests = TokenBuckets(rate=1, burst=1, capacity=1)
_MAX_UPSTREAM_BYTES = 256 * 1024


@contextmanager
def _upstream_budget(limiter):
    if not _upstream_slots.acquire(blocking=False):
        raise HTTPException(503, "Weather service busy", headers={"Retry-After": "5"})
    try:
        if not limiter.allow("upstream"):
            raise HTTPException(429, "Weather request limit reached", headers={"Retry-After": "2"})
        yield
    finally:
        _upstream_slots.release()


def _read_upstream_json(response):
    import json

    content = response.read(_MAX_UPSTREAM_BYTES + 1)
    if len(content) > _MAX_UPSTREAM_BYTES:
        raise ValueError("Upstream response too large")
    payload = json.loads(content.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Invalid upstream response")
    return payload


def _clean_location_name(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())


def _pick_location_name(address: dict, display_name: str = "") -> str:
    # Ưu tiên cấp thành phố/tỉnh vì tên này vừa đủ ngắn để hiển thị trên appbar.
    for key in ("city", "municipality", "town", "state", "province", "county", "village"):
        name = _clean_location_name(address.get(key))
        if name:
            if name == "Thành phố Hồ Chí Minh":
                return "TP. Hồ Chí Minh"
            return name

    # Dự phòng cuối cùng: lấy phần đầu của display_name thay vì trả về
    # chuỗi chung chung "Vị trí hiện tại".
    first_part = _clean_location_name((display_name or "").split(",", 1)[0])
    return first_part


@router.get("/api/location-name")
def get_location_name(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
):
    """Resolve GPS coordinates to a short city/province name using OpenStreetMap Nominatim."""
    import urllib.parse
    import urllib.request

    latitude, longitude = round(latitude, 3), round(longitude, 3)
    cache_key = f"v1:{latitude},{longitude}"
    cached = _location_name_cache.get(cache_key)
    if cached is not None:
        return JSONResponse(
            {"name": cached, "cached": True},
            headers={"Cache-Control": "private, max-age=3600"},
        )

    params = urllib.parse.urlencode(
        {
            "format": "jsonv2",
            "lat": latitude,
            "lon": longitude,
            "zoom": 10,
            "addressdetails": 1,
            "accept-language": "vi",
        }
    )
    url = f"https://nominatim.openstreetmap.org/reverse?{params}"

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "TeacherTimetable/1.0 (weather location resolver)",
                "Accept": "application/json",
            },
        )
        with _upstream_budget(_location_requests):
            with urllib.request.urlopen(req, timeout=6) as resp:
                payload = _read_upstream_json(resp)

        address = payload.get("address") if isinstance(payload, dict) else {}
        if not isinstance(address, dict):
            address = {}
        name = _pick_location_name(address, payload.get("display_name", ""))
        if not name:
            return JSONResponse({"name": ""}, status_code=404)

        _location_name_cache.put(cache_key, name)
        return JSONResponse(
            {"name": name, "cached": False},
            headers={"Cache-Control": "private, max-age=3600"},
        )
    except HTTPException:
        raise
    except Exception:
        # Reverse geocoding chỉ phục vụ nhãn hiển thị; lỗi không được làm hỏng widget thời tiết.
        return JSONResponse({"name": "", "error": "Location service unavailable"}, status_code=502)


@router.get("/api/weather")
def get_weather(
    latitude: float = Query(21.0285, ge=-90, le=90),
    longitude: float = Query(105.8542, ge=-180, le=180),
):
    """Fetch current weather and 7-day forecast from Open-Meteo with caching."""
    import urllib.request

    latitude, longitude = round(latitude, 3), round(longitude, 3)
    cache_key = f"v1:{latitude},{longitude}"
    cached_data = _weather_cache.get(cache_key)
    if cached_data is not None:
        return JSONResponse(cached_data, headers={"Cache-Control": "public, max-age=600"})

    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={latitude}&longitude={longitude}"
        f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m"
        f"&hourly=weather_code,precipitation_probability,precipitation,is_day"
        f"&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,wind_speed_10m_max"
        f"&timezone=auto&forecast_days=7"
    )

    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "TeacherTimetable/1.0 (Open-Meteo Integration)"}
        )
        with _upstream_budget(_weather_requests):
            with urllib.request.urlopen(req, timeout=7) as resp:
                data = _read_upstream_json(resp)
        _weather_cache.put(cache_key, data)
        return JSONResponse(data, headers={"Cache-Control": "public, max-age=600"})
    except HTTPException:
        raise
    except Exception:
        return JSONResponse({"error": "Weather service unavailable"}, status_code=502)
