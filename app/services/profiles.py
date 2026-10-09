"""Validate Facebook profile links without fetching remote content."""
from urllib.parse import urlsplit


def normalize_profile_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if len(value) > 2048:
        raise ValueError("URL hồ sơ Facebook không được dài quá 2048 ký tự.")
    message = "URL hồ sơ Facebook không hợp lệ."
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value) or "\\" in value:
        raise ValueError(message)
    try:
        parsed = urlsplit(value)
        parsed.port
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            raise ValueError(message)
        hostname = parsed.hostname.lower()
        if not any(hostname == domain or hostname.endswith("." + domain)
                   for domain in ("facebook.com", "fb.com")):
            raise ValueError(message)
        if parsed.port not in (None, 80, 443):
            raise ValueError(message)
    except ValueError:
        raise ValueError(message) from None
    return value
