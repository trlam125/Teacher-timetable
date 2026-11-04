from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote
import asyncio
import hashlib
import io
import json
import logging
import os
import secrets
import threading
import time

from fastapi import (
    Depends,
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
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired
from pydantic import BaseModel, Field
from sqlalchemy import (
    delete,
    func,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
import psycopg

from app.config import (
    DATABASE_BOOTSTRAP_LOCK_TIMEOUT_SECONDS,
    DATABASE_DDL_LOCK_TIMEOUT_SECONDS,
    DATABASE_STATEMENT_TIMEOUT_SECONDS,
    DATABASE_URL,
)
from app.database import DATABASE_BOOTSTRAP_LOCK_KEY, SessionLocal, engine
from app.logging_config import logger
from app.logic import (
    fixed_group_validation_error,
    normalize_slot_values,
)
from app.models import (
    Base,
    User,
    RealtimeConnection,
    RealtimeEvent,
    EmailChangeVerification,
    School,
    UserSchool,
    Project,
    Department,
    Subject,
    Teacher,
    TeacherSubject,
    Grade,
    GradeSubjectRequirement,
    SchoolClass,
    Assignment,
    FixedLesson,
    Lesson,
    TeacherPreference,
    ChatbotErrorLog,
    ChatMessage,
)
from app.scheduling.rules import (
    all_slots,
    assignment_groups,
    assignment_requires_double,
    bounded_int,
    class_blocked_slots,
    class_grade_blocked_slots,
    ensure_assignment_hard_feasible,
    fixed_row_size,
    normalized_block_mode,
    parse_slots,
    required_double_block_state,
    next_required_double_block_size,
    slot_meta,
    valid_slots,
)
from app.scheduling.solver import ga_schedule
from app.settings import (
    ADMIN_ROLES,
    APP_BASE_URL,
    APP_ENV,
    BOOTSTRAP_ADMIN_EMAIL,
    BOOTSTRAP_ADMIN_PASSWORD,
    DAYS,
    EMAIL_CHANGE_CONFIRM_TTL_SECONDS,
    EMAIL_CHANGE_OTP_MAX_ATTEMPTS,
    EMAIL_CHANGE_OTP_TTL_SECONDS,
    MAX_CHATBOT_DOCUMENT_CONTEXT_CHARS,
    MAX_CHATBOT_ERROR_LOGS,
    MAX_SCHEDULE_AUDIT_FILE_BYTES,
    MIN_PASSWORD_LENGTH,
    REGISTRATION_OTP_MAX_ATTEMPTS,
    REGISTRATION_OTP_RESEND_SECONDS,
    REGISTRATION_OTP_TTL_SECONDS,
    RESET_TOKEN_TTL_SECONDS,
    SEED_DEMO_DATA,
    SESSION_TTL_SECONDS,
    SUPER_ADMIN_USER_ID,
    VIETNAM_TZ,
)


__all__ = [name for name in globals() if not name.startswith("__")]
