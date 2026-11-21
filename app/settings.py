"""Application settings shared without importing database/session services."""
from __future__ import annotations

from datetime import timedelta, timezone
import os

from dotenv import load_dotenv

load_dotenv()

ADMIN_ROLES = frozenset({"admin", "super_admin"})
MAX_SYSTEM_INCIDENT_LOGS = 500
MAX_CHATBOT_DOCUMENT_CONTEXT_CHARS = 350_000
MAX_SCHEDULE_AUDIT_FILE_BYTES = 15 * 1024 * 1024
NVIDIA_DEFAULT_MODEL = "google/gemma-4-31b-it"
VIETNAM_TZ = timezone(timedelta(hours=7), name="UTC+7")

DAYS = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]
RESET_TOKEN_TTL_SECONDS = 30 * 60
REGISTRATION_OTP_TTL_SECONDS = 10 * 60
REGISTRATION_OTP_RESEND_SECONDS = 60
REGISTRATION_OTP_MAX_ATTEMPTS = 5
EMAIL_CHANGE_CONFIRM_TTL_SECONDS = 10 * 60
EMAIL_CHANGE_OTP_TTL_SECONDS = 10 * 60
EMAIL_CHANGE_OTP_MAX_ATTEMPTS = 5
MIN_PASSWORD_LENGTH = 8
SESSION_TTL_SECONDS = max(300, int(os.getenv("SESSION_TTL_SECONDS", str(12 * 60 * 60))))
HTTP_MAX_BODY_BYTES = max(1024, int(os.getenv("HTTP_MAX_BODY_BYTES", str(32 * 1024 * 1024))))
HTTP_BODY_TIMEOUT_SECONDS = max(1, float(os.getenv("HTTP_BODY_TIMEOUT_SECONDS", "30")))
HTTP_RATE_PER_MINUTE = max(1, int(os.getenv("HTTP_RATE_PER_MINUTE", "600")))
HTTP_RATE_BURST = max(1, int(os.getenv("HTTP_RATE_BURST", "120")))
HTTP_MAX_CONCURRENT = max(1, int(os.getenv("HTTP_MAX_CONCURRENT", "64")))
HTTP_MAX_BODY_CONCURRENT = max(1, int(os.getenv("HTTP_MAX_BODY_CONCURRENT", "4")))
WS_MAX_CONNECTIONS = max(1, int(os.getenv("WS_MAX_CONNECTIONS", "128")))
WS_MAX_CONNECTIONS_PER_USER = max(1, int(os.getenv("WS_MAX_CONNECTIONS_PER_USER", "8")))
WS_MAX_CONNECTIONS_PER_IP = max(1, int(os.getenv("WS_MAX_CONNECTIONS_PER_IP", "16")))
WS_MAX_MESSAGE_BYTES = max(1024, int(os.getenv("WS_MAX_MESSAGE_BYTES", "32768")))
WS_EVENTS_PER_MINUTE = max(1, int(os.getenv("WS_EVENTS_PER_MINUTE", "120")))
WS_EVENT_BURST = max(1, int(os.getenv("WS_EVENT_BURST", "30")))
APP_ENV = os.getenv("APP_ENV", "production").strip().lower()
APP_BASE_URL = os.getenv("APP_BASE_URL", "").strip().rstrip("/")
BOOTSTRAP_ADMIN_EMAIL = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
BOOTSTRAP_ADMIN_PASSWORD = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
try:
    SUPER_ADMIN_USER_ID = int(os.getenv("SUPER_ADMIN_USER_ID", "0") or 0)
except ValueError:
    SUPER_ADMIN_USER_ID = 0
SEED_DEMO_DATA = os.getenv("SEED_DEMO_DATA", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}


def nvidia_api_key() -> str:
    return os.getenv("NVIDIA_API_KEY", "").strip()


def nvidia_primary_model() -> str:
    return os.getenv("NVIDIA_MODEL", "").strip() or NVIDIA_DEFAULT_MODEL
