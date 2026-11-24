"""Normalize outbound teaching links only. Never fetch a user-provided URL."""
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

POLICY = json.loads((Path(__file__).resolve().parents[2] / 'static/ai-slides/link-policy.json').read_text())


def normalize_link(value):
    if not isinstance(value, str) or len(value) > 1000 or re.search(r'[\x00-\x20\x7f\\]', value):
        raise ValueError('Liên kết không hợp lệ.')
    try:
        url = urlsplit(value)
        if url.scheme != 'https' or url.username or url.password or url.port not in (None, 443):
            raise ValueError
        host = url.hostname
        if host in POLICY['youtube_hosts']:
            video = url.path[1:] if host == 'youtu.be' else parse_qs(url.query).get('v', [''])[0] if url.path == '/watch' else url.path.split('/')[-1] if url.path.startswith(('/shorts/', '/embed/')) else ''
            if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video):
                raise ValueError
            return 'https://www.youtube.com/watch?v=' + video, 'video'
        if host in POLICY['vimeo_hosts'] and re.fullmatch(r'/[0-9]{1,12}', url.path):
            return 'https://vimeo.com' + url.path, 'video'
        if host in POLICY['web_hosts']:
            return 'https://' + host + (url.path or '/'), 'web'
    except (ValueError, TypeError):
        pass
    raise ValueError('Chỉ nhận HTTPS từ YouTube, Vimeo, PhET, NASA, Wikipedia tiếng Việt, Khan Academy hoặc Bộ GDĐT. Liên kết video cần đúng mã video.')
