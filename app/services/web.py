from __future__ import annotations

from app.services.foundation import *

templates = Jinja2Templates(directory="app/templates")

def redirect_with_notice(
    path: str, message: str, kind: str = "error", **extra_params: str | int
) -> RedirectResponse:
    """Redirect an HTML form back to its page with a one-shot toast message."""
    params = [
        f"notice={quote(str(message), safe='')}",
        f"notice_type={quote(str(kind), safe='')}",
    ]
    for key, value in extra_params.items():
        params.append(f"{quote(str(key), safe='')}={quote(str(value), safe='')}")
    separator = "&" if "?" in path else "?"
    return RedirectResponse(f"{path}{separator}{'&'.join(params)}", 303)

def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None

def format_last_seen(value: str | None) -> str:
    parsed = _parse_iso_datetime(value)
    if parsed is None:
        return "Chưa có hoạt động"
    delta = max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))
    if delta < 60:
        return "Vừa xong"
    if delta < 3600:
        return f"{delta // 60} phút trước"
    if delta < 86400:
        return f"{delta // 3600} giờ trước"
    if delta < 172800:
        return "Hôm qua"
    return parsed.astimezone(VIETNAM_TZ).strftime("%d/%m/%Y %H:%M")

def format_vietnam_datetime(value: str | None) -> str:
    """Format an ISO timestamp in Vietnam time (UTC+7)."""
    parsed = _parse_iso_datetime(value)
    if parsed is None:
        return value or "-"
    return parsed.astimezone(VIETNAM_TZ).strftime("%d/%m/%Y %H:%M:%S")

templates.env.filters["timeago"] = format_last_seen
templates.env.filters["vietnam_datetime"] = format_vietnam_datetime


def bounded_text(value, label: str, max_length: int, *, required: bool = True) -> str:
    cleaned = str(value or "").strip()
    if required and not cleaned:
        raise HTTPException(400, f"{label} không được để trống")
    if len(cleaned) > max_length:
        raise HTTPException(400, f"{label} không được vượt quá {max_length} ký tự")
    return cleaned


__all__ = [name for name in globals() if not name.startswith('__')]
