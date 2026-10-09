"""Validate user-supplied avatar URLs without fetching remote content."""
from urllib.parse import urlsplit


def normalize_profile_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if len(value) > 2048:
        raise ValueError("URL ảnh đại diện không được dài quá 2048 ký tự.")
    message = "URL ảnh đại diện phải là link http:// hoặc https:// hợp lệ."
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value) or "\\" in value:
        raise ValueError(message)
    try:
        parsed = urlsplit(value)
        parsed.port
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            raise ValueError(message)
    except ValueError:
        raise ValueError(message) from None
    return value
