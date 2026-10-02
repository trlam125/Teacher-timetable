from __future__ import annotations

from fastapi import APIRouter, Query
from app.services.runtime import *

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


_weather_cache: dict[str, tuple[dict, float]] = {}
_WEATHER_CACHE_TTL = 600.0  # 10 minutes cache


_location_name_cache: dict[str, tuple[str, float]] = {}
_LOCATION_NAME_CACHE_TTL = 86400.0  # 24 hours


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
    import json
    import urllib.parse
    import urllib.request

    cache_key = f"{round(latitude, 3)},{round(longitude, 3)}"
    now = time.time()
    cached = _location_name_cache.get(cache_key)
    if cached and now - cached[1] < _LOCATION_NAME_CACHE_TTL:
        return JSONResponse(
            {"name": cached[0], "cached": True},
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
        with urllib.request.urlopen(req, timeout=6) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        address = payload.get("address") if isinstance(payload, dict) else {}
        if not isinstance(address, dict):
            address = {}
        name = _pick_location_name(address, payload.get("display_name", ""))
        if not name:
            return JSONResponse({"name": ""}, status_code=404)

        _location_name_cache[cache_key] = (name, now)
        return JSONResponse(
            {"name": name, "cached": False},
            headers={"Cache-Control": "private, max-age=3600"},
        )
    except Exception as exc:
        # Reverse geocoding chỉ phục vụ nhãn hiển thị; lỗi không được làm hỏng widget thời tiết.
        if cached:
            return JSONResponse({"name": cached[0], "cached": True})
        return JSONResponse({"name": "", "error": str(exc)}, status_code=502)


@router.get("/api/weather")
def get_weather(
    latitude: float = Query(21.0285, ge=-90, le=90),
    longitude: float = Query(105.8542, ge=-180, le=180),
):
    """Fetch current weather and 7-day forecast from Open-Meteo with caching."""
    import urllib.request
    import json

    cache_key = f"{round(latitude, 3)},{round(longitude, 3)}"
    now = time.time()

    if cache_key in _weather_cache:
        cached_data, timestamp = _weather_cache[cache_key]
        if now - timestamp < _WEATHER_CACHE_TTL:
            return JSONResponse(
                cached_data, headers={"Cache-Control": "public, max-age=600"}
            )

    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={latitude}&longitude={longitude}"
        f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m"
        f"&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max"
        f"&timezone=auto&forecast_days=7"
    )

    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "TeacherTimetable/1.0 (Open-Meteo Integration)"}
        )
        with urllib.request.urlopen(req, timeout=7) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            _weather_cache[cache_key] = (data, now)
            return JSONResponse(data, headers={"Cache-Control": "public, max-age=600"})
    except Exception as e:
        if cache_key in _weather_cache:
            data, _ = _weather_cache[cache_key]
            return JSONResponse(data)
        return JSONResponse({"error": str(e)}, status_code=502)
