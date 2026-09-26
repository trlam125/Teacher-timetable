from __future__ import annotations

import asyncio
import io
import base64
import json
import logging
import random
import secrets
import smtplib
import time
import threading
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Optional

from app.config import (
    DATABASE_BOOTSTRAP_LOCK_TIMEOUT_SECONDS,
    DATABASE_DDL_LOCK_TIMEOUT_SECONDS,
    DATABASE_STATEMENT_TIMEOUT_SECONDS,
    DATABASE_URL,
    SECRET_KEY,
)
from app.database import DATABASE_BOOTSTRAP_LOCK_KEY, SessionLocal, engine
from app.models import (
    Base, User, RealtimeConnection, RealtimeEvent, RegistrationVerification,
    EmailChangeVerification, School, UserSchool, Project, CaptchaUse,
    RateLimitBucket, Department, Subject, Teacher, TeacherSubject, Grade,
    GradeSubjectRequirement, SchoolClass, Assignment, FixedLesson, Lesson,
    TeacherPreference, ChatbotErrorLog, ChatMessage, SystemSetting,
)
from app.scheduling.rules import (
    all_slots, assignment_generated_pattern, assignment_groups,
    assignment_pattern_matches, assignment_prefers_double,
    assignment_requires_double, assignment_run_groups, bounded_int,
    ensure_assignment_hard_feasible, ensure_required_double_hard_feasible,
    fixed_row_size, normalized_block_mode,
    parse_slots, pattern_completion_plan, pattern_slots_match,
    preferred_double_pair_count, remaining_pattern_groups,
    required_double_hard_feasible,
    required_double_block_state, next_required_double_block_size,
    required_double_structure_feasible, slot_meta, timetable_pattern_feasible,
    valid_slots,
)
from app.scheduling.solver import ga_schedule, solve, solve_missing, solve_rebuild

from app.logic import (
    fixed_group_validation_error,
    normalize_slot_values,
    parse_integer_set,
    pop_matching_fixed_task,
    remap_slot_for_session_expansion,
    remap_slots_for_session_expansion,
    schedule_validation_peers,
)
from urllib.parse import quote

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
import hashlib
import hmac
import os
import psycopg
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field
from sqlalchemy import (
    delete,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

logger = logging.getLogger("smart_tkb")

ADMIN_ROLES = frozenset({"admin", "super_admin"})
MAX_CHATBOT_ERROR_LOGS = 500
MAX_CHATBOT_DOCUMENT_CONTEXT_CHARS = 350_000
MAX_SCHEDULE_AUDIT_FILE_BYTES = 15 * 1024 * 1024
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



__all__ = [name for name in globals() if not name.startswith('__')]
