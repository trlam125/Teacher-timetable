"""Explicit compatibility exports for this package."""
from app.services.realtime.manager import RealtimeConnectionManager, realtime_manager
from app.services.realtime.presence import _broadcast_delayed_offline, broadcast_school_presence
from app.services.realtime.utils import (
    _payload_school_id,
    _utc_now_iso,
    presence_recipients_for_user,
    presence_visible_user_ids,
    school_chat_user_ids,
    touch_user_last_seen,
    websocket_session_user,
)

__all__ = [
    'RealtimeConnectionManager', '_broadcast_delayed_offline', '_payload_school_id',
    '_utc_now_iso', 'broadcast_school_presence', 'presence_recipients_for_user',
    'presence_visible_user_ids', 'realtime_manager', 'school_chat_user_ids',
    'touch_user_last_seen', 'websocket_session_user',
]
