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

from app.logic import (
    fixed_group_validation_error,
    normalize_slot_values,
    parse_integer_set,
    pop_matching_fixed_task,
    remap_slot_for_session_expansion,
    remap_slots_for_session_expansion,
    required_double_removal_slots,
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
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

load_dotenv()

logger = logging.getLogger("smart_tkb")

ADMIN_ROLES = frozenset({"admin", "super_admin"})
MAX_CHATBOT_ERROR_LOGS = 500
MAX_CHATBOT_DOCUMENT_CONTEXT_CHARS = 350_000
MAX_SCHEDULE_AUDIT_FILE_BYTES = 15 * 1024 * 1024
VIETNAM_TZ = timezone(timedelta(hours=7), name="UTC+7")

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY")

if not DATABASE_URL:
    raise RuntimeError(
        "Thiếu DATABASE_URL. Hãy tạo file .env dựa trên .env.example "
        "và nhập chuỗi kết nối PostgreSQL."
    )
if not DATABASE_URL.startswith(("postgresql://", "postgresql+psycopg://")):
    raise RuntimeError("Project này chỉ hỗ trợ PostgreSQL.")
if not SECRET_KEY:
    raise RuntimeError("Thiếu SECRET_KEY. Hãy tạo khóa bí mật và thêm vào file .env.")

# Chuẩn hóa về driver psycopg 3.
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

DATABASE_CONNECT_TIMEOUT_SECONDS = 10
DATABASE_BOOTSTRAP_LOCK_TIMEOUT_SECONDS = 15
DATABASE_DDL_LOCK_TIMEOUT_SECONDS = 8
DATABASE_STATEMENT_TIMEOUT_SECONDS = 30

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_timeout=DATABASE_CONNECT_TIMEOUT_SECONDS,
    connect_args={"connect_timeout": DATABASE_CONNECT_TIMEOUT_SECONDS},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
DATABASE_BOOTSTRAP_LOCK_KEY = 73120260903


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120), default="Giáo viên")
    role: Mapped[str] = mapped_column(String(20), default="teacher")
    reset_token_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reset_token_expires_at: Mapped[Optional[str]] = mapped_column(
        String(40), nullable=True
    )
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False)
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    last_seen: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)


class RealtimeConnection(Base):
    __tablename__ = "realtime_connections"
    connection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    instance_id: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[str] = mapped_column(String(40), index=True)


class RealtimeEvent(Base):
    """Short-lived cross-worker payloads; NOTIFY carries only the event ID."""

    __tablename__ = "realtime_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    envelope_json: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[int] = mapped_column(Integer, index=True)


class RegistrationVerification(Base):
    __tablename__ = "registration_verifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    otp_hash: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[str] = mapped_column(String(40))
    resend_available_at: Mapped[str] = mapped_column(String(40))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(
        String(40), default=lambda: datetime.now(timezone.utc).isoformat()
    )


class EmailChangeVerification(Base):
    __tablename__ = "email_change_verifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, index=True
    )
    requested_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True
    )
    new_email: Mapped[str] = mapped_column(String(255), index=True)
    otp_hash: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[str] = mapped_column(String(40))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(
        String(40), default=lambda: datetime.now(timezone.utc).isoformat()
    )


class School(Base):
    __tablename__ = "schools"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    created_at: Mapped[str] = mapped_column(
        String(40), default=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )


class UserSchool(Base):
    __tablename__ = "user_schools"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), primary_key=True)
    assigned_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    assigned_at: Mapped[str] = mapped_column(
        String(40), default=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    school_id: Mapped[Optional[int]] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    school_name: Mapped[str] = mapped_column(String(200), default="Trường học")
    days: Mapped[int] = mapped_column(Integer, default=6)
    sessions: Mapped[int] = mapped_column(Integer, default=2)
    periods_per_session: Mapped[int] = mapped_column(Integer, default=5)
    blocked_slots_json: Mapped[str] = mapped_column(Text, default="[]")
    share_token: Mapped[str] = mapped_column(
        String(64), unique=True, default=lambda: secrets.token_urlsafe(16)
    )
    created_at: Mapped[str] = mapped_column(
        String(40), default=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )


class CaptchaUse(Base):
    __tablename__ = "captcha_uses"
    nonce_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(40), index=True)
    used_at: Mapped[int] = mapped_column(Integer, index=True)


class RateLimitBucket(Base):
    __tablename__ = "rate_limit_buckets"
    bucket_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    window_started_at: Mapped[int] = mapped_column(Integer)
    count: Mapped[int] = mapped_column(Integer, default=0)
    touched_at: Mapped[int] = mapped_column(Integer, index=True)


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))


class Subject(Base):
    __tablename__ = "subjects"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    short_name: Mapped[str] = mapped_column(String(20))
    max_consecutive: Mapped[int] = mapped_column(Integer, default=2)


class Teacher(Base):
    __tablename__ = "teachers"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    department_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("departments.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(120))
    short_name: Mapped[str] = mapped_column(String(30))
    max_periods_day: Mapped[int] = mapped_column(Integer, default=5)
    unavailable_json: Mapped[str] = mapped_column(Text, default="[]")


class TeacherSubject(Base):
    __tablename__ = "teacher_subjects"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    __table_args__ = (
        UniqueConstraint(
            "project_id", "teacher_id", "subject_id", name="uq_teacher_subject"
        ),
    )


class Grade(Base):
    __tablename__ = "grades"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))


class GradeSubjectRequirement(Base):
    __tablename__ = "grade_subject_requirements"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    grade_id: Mapped[int] = mapped_column(ForeignKey("grades.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    periods_per_week: Mapped[int] = mapped_column(Integer, default=1)
    block_mode: Mapped[str] = mapped_column(String(24), default="free")
    __table_args__ = (
        UniqueConstraint(
            "project_id", "grade_id", "subject_id", name="uq_grade_subject_requirement"
        ),
    )


class SchoolClass(Base):
    __tablename__ = "classes"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    grade_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("grades.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(80))
    unavailable_json: Mapped[str] = mapped_column(Text, default="[]")


class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"))
    periods_per_week: Mapped[int] = mapped_column(Integer, default=1)
    block_mode: Mapped[str] = mapped_column(String(24), default="free")
    # Giữ cột cũ để migration các project đã tồn tại; giao diện mới không dùng mẫu chuỗi.
    consecutive_pattern: Mapped[str] = mapped_column(String(80), default="")
    __table_args__ = (
        UniqueConstraint(
            "project_id", "class_id", "subject_id", name="uq_assignment_class_subject"
        ),
    )


class FixedLesson(Base):
    __tablename__ = "fixed_lessons"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"))
    slot: Mapped[int] = mapped_column(Integer)
    group_size: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        UniqueConstraint("project_id", "assignment_id", "slot", name="uq_fixed_lesson"),
    )


class Lesson(Base):
    __tablename__ = "lessons"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"))
    slot: Mapped[int] = mapped_column(Integer)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        UniqueConstraint("project_id", "assignment_id", "slot", name="uq_lesson"),
    )


class TeacherPreference(Base):
    __tablename__ = "teacher_preferences"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    # teacher_id chỉ còn phục vụ dữ liệu legacy. Nguyện vọng mới gắn với tài
    # khoản đã xác minh email, tránh khôi phục cơ chế gán account -> Teacher.
    teacher_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("teachers.id"), nullable=True, index=True
    )
    submitted_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
            name="fk_teacher_preferences_submitted_by_user_id",
        ),
        nullable=True,
        index=True,
    )
    submitted_name: Mapped[str] = mapped_column(String(120), default="")
    submitted_email: Mapped[str] = mapped_column(String(255), default="")
    preferred_json: Mapped[str] = mapped_column(Text, default="[]")
    unavailable_json: Mapped[str] = mapped_column(Text, default="[]")
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    created_at: Mapped[str] = mapped_column(
        String(40), default=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    reviewed_at: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)


class ChatbotErrorLog(Base):
    __tablename__ = "chatbot_error_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[str] = mapped_column(
        String(40),
        default=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"),
        index=True,
    )
    project_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )
    project_name: Mapped[str] = mapped_column(String(200), default="")
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    user_name: Mapped[str] = mapped_column(String(120), default="")
    user_email: Mapped[str] = mapped_column(String(255), default="")
    error_code: Mapped[str] = mapped_column(
        String(64), default="chatbot_error", index=True
    )
    provider_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str] = mapped_column(Text)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[Optional[int]] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    user_name: Mapped[str] = mapped_column(String(120), default="")
    user_email: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[str] = mapped_column(Text)
    reply_to_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[str] = mapped_column(
        String(40),
        default=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"),
        index=True,
    )
    edited_at: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    deleted_at: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[str] = mapped_column(
        String(40),
        default=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def migrate_schema():
    """Nâng cấp schema PostgreSQL và loại bỏ cấu trúc liên kết tài khoản giáo viên cũ."""
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"SET LOCAL lock_timeout = '{DATABASE_DDL_LOCK_TIMEOUT_SECONDS}s'"
        )
        connection.exec_driver_sql(
            f"SET LOCAL statement_timeout = '{DATABASE_STATEMENT_TIMEOUT_SECONDS}s'"
        )
        inspector = inspect(connection)
        if "users" not in inspector.get_table_names():
            return

        columns = {column["name"] for column in inspector.get_columns("users")}
        role_was_added = "role" not in columns
        if role_was_added:
            connection.exec_driver_sql(
                "ALTER TABLE users "
                "ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'teacher'"
            )
        if "reset_token_hash" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN reset_token_hash VARCHAR(64)"
            )
        if "reset_token_expires_at" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN reset_token_expires_at VARCHAR(40)"
            )
        if "is_superadmin" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN is_superadmin BOOLEAN NOT NULL DEFAULT FALSE"
            )
        if "session_version" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1"
            )
        if "last_seen" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN last_seen VARCHAR(40)"
            )

        if "projects" in inspector.get_table_names():
            project_columns = {
                column["name"] for column in inspector.get_columns("projects")
            }
            if "school_id" not in project_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE projects ADD COLUMN school_id INTEGER"
                )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_projects_school_id ON projects (school_id)"
            )
            # Chuẩn hóa các tên trường đã có thành bảng schools. Việc gán trường
            # cho tài khoản vẫn để quản trị viên thực hiện thủ công ở Quản lý tài khoản.
            connection.exec_driver_sql(
                "INSERT INTO schools (name, created_at) "
                "SELECT DISTINCT TRIM(school_name), %s FROM projects "
                "WHERE school_name IS NOT NULL AND TRIM(school_name)<>'' "
                "ON CONFLICT (name) DO NOTHING",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"),),
            )
            connection.exec_driver_sql(
                "UPDATE projects p SET school_id=s.id FROM schools s "
                "WHERE p.school_id IS NULL AND TRIM(p.school_name)=s.name"
            )

        if "chat_messages" in inspector.get_table_names():
            chat_columns = {
                column["name"] for column in inspector.get_columns("chat_messages")
            }
            if "school_id" not in chat_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE chat_messages ADD COLUMN school_id INTEGER"
                )
            if "reply_to_id" not in chat_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE chat_messages ADD COLUMN reply_to_id INTEGER"
                )
            if "edited_at" not in chat_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE chat_messages ADD COLUMN edited_at VARCHAR(40)"
                )
            if "deleted_at" not in chat_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE chat_messages ADD COLUMN deleted_at VARCHAR(40)"
                )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_chat_messages_reply_to_id "
                "ON chat_messages (reply_to_id)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_chat_messages_school_id "
                "ON chat_messages (school_id)"
            )
        connection.exec_driver_sql(
            "UPDATE users SET role='teacher' WHERE role IS NULL OR role='' OR role IN ('user', 'pending')"
        )
        bootstrap_email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
        try:
            configured_super_admin_id = int(os.getenv("SUPER_ADMIN_USER_ID", "0") or 0)
        except ValueError:
            configured_super_admin_id = 0

        configured_super_admin_exists = False
        if configured_super_admin_id > 0:
            configured_super_admin_exists = (
                connection.exec_driver_sql(
                    "SELECT 1 FROM users WHERE id=%s",
                    (configured_super_admin_id,),
                ).first()
                is not None
            )
            if not configured_super_admin_exists:
                logger.error(
                    "SUPER_ADMIN_USER_ID=%s không tồn tại; giữ nguyên super_admin hiện tại.",
                    configured_super_admin_id,
                )

        existing_super_admin_id = connection.exec_driver_sql(
            "SELECT id FROM users WHERE role='super_admin' ORDER BY id ASC LIMIT 1"
        ).scalar()
        bootstrap_super_admin_exists = False
        # BOOTSTRAP_ADMIN_EMAIL chỉ dùng để khởi tạo/khôi phục khi database chưa
        # có super_admin. Sau khi super admin đổi email, không được tạo lại tài
        # khoản email bootstrap cũ rồi hạ quyền tài khoản hiện tại.
        if (
            configured_super_admin_id <= 0
            and existing_super_admin_id is None
            and bootstrap_email
        ):
            bootstrap_super_admin_exists = (
                connection.exec_driver_sql(
                    "SELECT 1 FROM users WHERE lower(email)=lower(%s)",
                    (bootstrap_email,),
                ).first()
                is not None
            )

        if "projects" in inspector.get_table_names():
            # Keep valid 5-7 day schedules intact. Only repair missing or
            # out-of-range legacy values so a 5-day project survives restarts.
            connection.exec_driver_sql(
                "UPDATE projects SET days=6 WHERE days IS NULL OR days<5 OR days>7"
            )

            connection.exec_driver_sql(
                "ALTER TABLE projects DROP COLUMN IF EXISTS teacher_invite_token"
            )

            # Chủ project thường giữ role admin. Chỉ hạ quyền super_admin khi
            # đã xác nhận chắc chắn tài khoản đích tồn tại; cấu hình sai không
            # được phép làm hệ thống mất toàn bộ super_admin.
            if configured_super_admin_exists:
                connection.exec_driver_sql(
                    "UPDATE users SET role='admin', is_superadmin=FALSE "
                    "WHERE id IN (SELECT DISTINCT owner_id FROM projects) AND id<>%s",
                    (configured_super_admin_id,),
                )
            elif configured_super_admin_id <= 0 and bootstrap_super_admin_exists:
                connection.exec_driver_sql(
                    "UPDATE users SET role='admin', is_superadmin=FALSE "
                    "WHERE id IN (SELECT DISTINCT owner_id FROM projects) "
                    "AND lower(email)<>lower(%s)",
                    (bootstrap_email,),
                )
            else:
                connection.exec_driver_sql(
                    "UPDATE users SET role='admin', is_superadmin=FALSE "
                    "WHERE id IN (SELECT DISTINCT owner_id FROM projects) "
                    "AND role<>'super_admin'"
                )
        if "registration_verifications" in inspector.get_table_names():
            connection.exec_driver_sql(
                "ALTER TABLE registration_verifications "
                "DROP COLUMN IF EXISTS project_id, "
                "DROP COLUMN IF EXISTS teacher_id, "
                "DROP COLUMN IF EXISTS requested_teacher_name"
            )
        if "teacher_account_links" in inspector.get_table_names():
            connection.exec_driver_sql("DROP TABLE teacher_account_links")
        # teacher_preferences được giữ lại có chủ đích như dữ liệu tham khảo.
        # Từ phiên bản này, nguyện vọng mới gắn với tài khoản đã xác minh email
        # thay vì hồ sơ Teacher, để không khôi phục cơ chế gán account -> Teacher.
        if "teacher_preferences" in inspector.get_table_names():
            preference_columns = {
                column["name"]
                for column in inspector.get_columns("teacher_preferences")
            }
            if "submitted_by_user_id" not in preference_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE teacher_preferences ADD COLUMN submitted_by_user_id INTEGER"
                )
            if "submitted_name" not in preference_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE teacher_preferences ADD COLUMN submitted_name VARCHAR(120) NOT NULL DEFAULT ''"
                )
            if "submitted_email" not in preference_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE teacher_preferences ADD COLUMN submitted_email VARCHAR(255) NOT NULL DEFAULT ''"
                )
            connection.exec_driver_sql(
                "ALTER TABLE teacher_preferences ALTER COLUMN teacher_id DROP NOT NULL"
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_teacher_preferences_submitted_by_user_id "
                "ON teacher_preferences (submitted_by_user_id)"
            )
            # Dữ liệu cũ có thể còn user_id trỏ tới tài khoản đã bị xóa.
            # Dọn các giá trị mồ côi trước khi bổ sung khóa ngoại để migration
            # chạy được trên database đang sử dụng.
            connection.exec_driver_sql(
                "UPDATE teacher_preferences preference "
                "SET submitted_by_user_id=NULL "
                "WHERE submitted_by_user_id IS NOT NULL "
                "AND NOT EXISTS ("
                "SELECT 1 FROM users WHERE users.id=preference.submitted_by_user_id"
                ")"
            )
            connection.exec_driver_sql(
                "DO $$ "
                "BEGIN "
                "IF NOT EXISTS ("
                "SELECT 1 FROM pg_constraint "
                "WHERE conname='fk_teacher_preferences_submitted_by_user_id'"
                ") THEN "
                "ALTER TABLE teacher_preferences "
                "ADD CONSTRAINT fk_teacher_preferences_submitted_by_user_id "
                "FOREIGN KEY (submitted_by_user_id) REFERENCES users(id) "
                "ON DELETE SET NULL; "
                "END IF; "
                "END $$"
            )
        # Không migrate nguyện vọng thành teacher.unavailable_json và không dùng
        # chúng làm ràng buộc xếp lịch.
        connection.exec_driver_sql(
            "ALTER TABLE users ALTER COLUMN role SET DEFAULT 'teacher'"
        )
        if configured_super_admin_exists:
            connection.exec_driver_sql(
                "UPDATE users SET role=CASE WHEN role='super_admin' THEN 'admin' ELSE role END, "
                "is_superadmin=FALSE WHERE id<>%s",
                (configured_super_admin_id,),
            )
            connection.exec_driver_sql(
                "UPDATE users SET role='super_admin', is_superadmin=TRUE WHERE id=%s",
                (configured_super_admin_id,),
            )
        elif configured_super_admin_id <= 0 and bootstrap_super_admin_exists:
            connection.exec_driver_sql(
                "UPDATE users SET role=CASE WHEN role='super_admin' THEN 'admin' ELSE role END, "
                "is_superadmin=FALSE WHERE lower(email)<>lower(%s)",
                (bootstrap_email,),
            )
            connection.exec_driver_sql(
                "UPDATE users SET role='super_admin', is_superadmin=TRUE "
                "WHERE lower(email)=lower(%s)",
                (bootstrap_email,),
            )

        connection.exec_driver_sql(
            "ALTER TABLE users "
            "DROP COLUMN IF EXISTS teacher_id, "
            "DROP COLUMN IF EXISTS requested_teacher_name, "
            "DROP COLUMN IF EXISTS requested_project_id"
        )

        # Từ phiên bản này, môn giáo viên có thể dạy được lưu riêng. Với dữ
        # liệu cũ, suy ra quan hệ này từ các phân công đã tồn tại để nâng cấp
        # không làm mất khả năng chỉnh sửa/xếp lịch của project hiện hữu.
        if (
            "teacher_subjects" in inspector.get_table_names()
            and "assignments" in inspector.get_table_names()
        ):
            connection.exec_driver_sql(
                "INSERT INTO teacher_subjects (project_id, teacher_id, subject_id) "
                "SELECT DISTINCT project_id, teacher_id, subject_id FROM assignments "
                "ON CONFLICT (project_id, teacher_id, subject_id) DO NOTHING"
            )

        if "assignments" in inspector.get_table_names():
            duplicate_assignment_pairs = connection.exec_driver_sql(
                "SELECT COUNT(*) FROM ("
                "SELECT project_id, class_id, subject_id FROM assignments "
                "GROUP BY project_id, class_id, subject_id HAVING COUNT(*) > 1"
                ") duplicate_pairs"
            ).scalar()
            if not duplicate_assignment_pairs:
                connection.exec_driver_sql(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_assignment_class_subject "
                    "ON assignments (project_id, class_id, subject_id)"
                )

        assignment_columns = (
            {column["name"] for column in inspector.get_columns("assignments")}
            if "assignments" in inspector.get_table_names()
            else set()
        )
        if assignment_columns and "block_mode" not in assignment_columns:
            connection.exec_driver_sql(
                "ALTER TABLE assignments ADD COLUMN block_mode VARCHAR(24) NOT NULL DEFAULT 'free'"
            )
            # Mẫu cũ chỉ gồm 1 và 2, đồng thời có ít nhất một số 2, được
            # chuyển sang bắt buộc tiết đôi. Mẫu có cụm 3+ chuyển thành tự do
            # vì chế độ mới không còn hỗ trợ cụm tùy ý.
            connection.exec_driver_sql(
                "UPDATE assignments SET block_mode='required_double' "
                "WHERE consecutive_pattern ~ '(^|,)[[:space:]]*2[[:space:]]*(,|$)' "
                "AND COALESCE(regexp_replace(consecutive_pattern, '[[:space:]12,]', '', 'g'), '') = ''"
            )
            connection.exec_driver_sql("UPDATE assignments SET consecutive_pattern=''")

        fixed_columns = (
            {column["name"] for column in inspector.get_columns("fixed_lessons")}
            if "fixed_lessons" in inspector.get_table_names()
            else set()
        )
        if fixed_columns and "group_size" not in fixed_columns:
            connection.exec_driver_sql(
                "ALTER TABLE fixed_lessons ADD COLUMN group_size INTEGER NOT NULL DEFAULT 1"
            )
        if fixed_columns:
            # Xóa bản ghi trùng do dữ liệu cũ/import thủ công rồi khóa bất biến
            # mỗi assignment chỉ có một FixedLesson tại cùng một slot.
            connection.exec_driver_sql(
                "DELETE FROM fixed_lessons newer USING fixed_lessons older "
                "WHERE newer.id>older.id "
                "AND newer.project_id=older.project_id "
                "AND newer.assignment_id=older.assignment_id "
                "AND newer.slot=older.slot"
            )
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_fixed_lesson "
                "ON fixed_lessons (project_id, assignment_id, slot)"
            )
        if fixed_columns and "assignments" in inspector.get_table_names():
            # Ở chế độ tự do/ưu tiên, mỗi ghim là một tiết độc lập. Chuyển các
            # ghim cụm cũ thành từng ghim đơn để không tạo tiết khóa mồ côi.
            connection.exec_driver_sql(
                "UPDATE fixed_lessons SET group_size=1 FROM assignments "
                "WHERE fixed_lessons.assignment_id=assignments.id "
                "AND assignments.block_mode<>'required_double'"
            )
            if "lessons" in inspector.get_table_names():
                connection.exec_driver_sql(
                    "INSERT INTO fixed_lessons (project_id, assignment_id, slot, group_size) "
                    "SELECT lessons.project_id, lessons.assignment_id, lessons.slot, 1 "
                    "FROM lessons JOIN assignments ON assignments.id=lessons.assignment_id "
                    "WHERE lessons.locked=TRUE AND assignments.block_mode<>'required_double' "
                    "AND NOT EXISTS (SELECT 1 FROM fixed_lessons "
                    "WHERE fixed_lessons.assignment_id=lessons.assignment_id "
                    "AND fixed_lessons.slot=lessons.slot)"
                )

        # Khóa tính toàn vẹn project ở tầng PostgreSQL. Các FK đơn chỉ chứng
        # minh bản ghi liên quan tồn tại, nhưng không chứng minh chúng thuộc
        # cùng project. Trigger dưới đây chặn dữ liệu chéo project kể cả khi
        # import trực tiếp hoặc có endpoint mới bỏ sót validation ứng dụng.
        if "assignments" in inspector.get_table_names():
            connection.exec_driver_sql(
                """
                CREATE OR REPLACE FUNCTION enforce_assignment_project_integrity()
                RETURNS trigger AS $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM classes WHERE id=NEW.class_id AND project_id=NEW.project_id) THEN
                        RAISE EXCEPTION 'Lớp không thuộc cùng project với phân công.' USING ERRCODE='23514';
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM subjects WHERE id=NEW.subject_id AND project_id=NEW.project_id) THEN
                        RAISE EXCEPTION 'Môn học không thuộc cùng project với phân công.' USING ERRCODE='23514';
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM teachers WHERE id=NEW.teacher_id AND project_id=NEW.project_id) THEN
                        RAISE EXCEPTION 'Giáo viên không thuộc cùng project với phân công.' USING ERRCODE='23514';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            )
            connection.exec_driver_sql(
                "DROP TRIGGER IF EXISTS trg_assignment_project_integrity ON assignments"
            )
            connection.exec_driver_sql(
                """
                CREATE TRIGGER trg_assignment_project_integrity
                BEFORE INSERT OR UPDATE OF project_id, class_id, subject_id, teacher_id
                ON assignments FOR EACH ROW
                EXECUTE FUNCTION enforce_assignment_project_integrity()
                """
            )
            invalid_assignments = connection.exec_driver_sql(
                """
                SELECT COUNT(*) FROM assignments a
                LEFT JOIN classes c ON c.id=a.class_id
                LEFT JOIN subjects s ON s.id=a.subject_id
                LEFT JOIN teachers t ON t.id=a.teacher_id
                WHERE c.id IS NULL OR s.id IS NULL OR t.id IS NULL
                   OR c.project_id<>a.project_id
                   OR s.project_id<>a.project_id
                   OR t.project_id<>a.project_id
                """
            ).scalar()
            if invalid_assignments:
                raise RuntimeError(
                    f"Phát hiện {invalid_assignments} phân công có tham chiếu chéo project. "
                    "Hãy sửa dữ liệu trước khi khởi động ứng dụng."
                )

        if "fixed_lessons" in inspector.get_table_names() and "assignments" in inspector.get_table_names():
            connection.exec_driver_sql(
                """
                CREATE OR REPLACE FUNCTION enforce_fixed_lesson_project_integrity()
                RETURNS trigger AS $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM assignments WHERE id=NEW.assignment_id AND project_id=NEW.project_id) THEN
                        RAISE EXCEPTION 'Tiết cố định và phân công không cùng project.' USING ERRCODE='23514';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            )
            connection.exec_driver_sql(
                "DROP TRIGGER IF EXISTS trg_fixed_lesson_project_integrity ON fixed_lessons"
            )
            connection.exec_driver_sql(
                """
                CREATE TRIGGER trg_fixed_lesson_project_integrity
                BEFORE INSERT OR UPDATE OF project_id, assignment_id
                ON fixed_lessons FOR EACH ROW
                EXECUTE FUNCTION enforce_fixed_lesson_project_integrity()
                """
            )
            invalid_fixed_lessons = connection.exec_driver_sql(
                """
                SELECT COUNT(*) FROM fixed_lessons f
                LEFT JOIN assignments a ON a.id=f.assignment_id
                WHERE a.id IS NULL OR a.project_id<>f.project_id
                """
            ).scalar()
            if invalid_fixed_lessons:
                raise RuntimeError(
                    f"Phát hiện {invalid_fixed_lessons} tiết cố định có tham chiếu chéo project. "
                    "Hãy sửa dữ liệu trước khi khởi động ứng dụng."
                )

        # Bảo vệ bất biến ở tầng PostgreSQL: tại một project/slot, một giáo
        # viên hoặc một lớp chỉ được xuất hiện trong tối đa một Lesson. Lesson
        # chỉ lưu assignment_id nên không thể diễn đạt hai UNIQUE constraint này
        # trực tiếp; trigger tra Assignment và dùng advisory lock theo project/slot
        # để cả import trực tiếp hoặc hai transaction đồng thời cũng không lọt.
        if (
            "lessons" in inspector.get_table_names()
            and "assignments" in inspector.get_table_names()
        ):
            invalid_lessons = connection.exec_driver_sql(
                """
                SELECT COUNT(*) FROM lessons l
                LEFT JOIN assignments a ON a.id=l.assignment_id
                WHERE a.id IS NULL OR a.project_id<>l.project_id
                """
            ).scalar()
            if invalid_lessons:
                raise RuntimeError(
                    f"Phát hiện {invalid_lessons} tiết học có tham chiếu chéo project. "
                    "Hãy sửa dữ liệu trước khi khởi động ứng dụng."
                )
            connection.exec_driver_sql(
                """
                CREATE OR REPLACE FUNCTION enforce_lesson_timetable_conflict()
                RETURNS trigger AS $$
                DECLARE
                    new_teacher_id INTEGER;
                    new_class_id INTEGER;
                    assignment_project_id INTEGER;
                BEGIN
                    SELECT teacher_id, class_id, project_id
                    INTO new_teacher_id, new_class_id, assignment_project_id
                    FROM assignments
                    WHERE id = NEW.assignment_id;

                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'Phân công %% không tồn tại.', NEW.assignment_id
                            USING ERRCODE = '23503';
                    END IF;

                    IF assignment_project_id <> NEW.project_id THEN
                        RAISE EXCEPTION 'Lesson và phân công không cùng project.'
                            USING ERRCODE = '23514';
                    END IF;

                    PERFORM pg_advisory_xact_lock(NEW.project_id, NEW.slot);

                    IF EXISTS (
                        SELECT 1
                        FROM lessons l
                        JOIN assignments a ON a.id = l.assignment_id
                        WHERE l.project_id = NEW.project_id
                          AND l.slot = NEW.slot
                          AND l.id <> COALESCE(NEW.id, -1)
                          AND a.teacher_id = new_teacher_id
                    ) THEN
                        RAISE EXCEPTION 'Giáo viên đã có tiết khác tại slot %%.', NEW.slot
                            USING ERRCODE = '23505';
                    END IF;

                    IF EXISTS (
                        SELECT 1
                        FROM lessons l
                        JOIN assignments a ON a.id = l.assignment_id
                        WHERE l.project_id = NEW.project_id
                          AND l.slot = NEW.slot
                          AND l.id <> COALESCE(NEW.id, -1)
                          AND a.class_id = new_class_id
                    ) THEN
                        RAISE EXCEPTION 'Lớp đã có tiết khác tại slot %%.', NEW.slot
                            USING ERRCODE = '23505';
                    END IF;

                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            )
            connection.exec_driver_sql(
                "DROP TRIGGER IF EXISTS trg_lesson_timetable_conflict ON lessons"
            )
            connection.exec_driver_sql(
                """
                CREATE TRIGGER trg_lesson_timetable_conflict
                BEFORE INSERT OR UPDATE OF project_id, assignment_id, slot
                ON lessons
                FOR EACH ROW
                EXECUTE FUNCTION enforce_lesson_timetable_conflict()
                """
            )

        # Bản demo rất cũ từng được tạo chỉ với một buổi. Đây là migration
        # thay đổi dữ liệu nên tuyệt đối không nhận diện project bằng tên/trường:
        # người dùng có thể tạo project thật trùng các giá trị đó. Chỉ migrate
        # các project_id được quản trị viên chỉ định rõ qua biến môi trường, và
        # lưu marker theo từng project để migration không thể chạy lặp.
        if "projects" in inspector.get_table_names():
            project_columns = {
                column["name"] for column in inspector.get_columns("projects")
            }
            if "blocked_slots_json" not in project_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE projects ADD COLUMN blocked_slots_json TEXT NOT NULL DEFAULT '[]'"
                )

            connection.exec_driver_sql(
                "CREATE TABLE IF NOT EXISTS app_data_migrations ("
                "migration_key VARCHAR(200) PRIMARY KEY, "
                "applied_at VARCHAR(40) NOT NULL"
                ")"
            )

            configured_ids = os.getenv("LEGACY_DEMO_SESSION_EXPANSION_PROJECT_IDS", "")
            legacy_demo_project_ids = set()
            for raw_id in configured_ids.split(","):
                raw_id = raw_id.strip()
                if not raw_id:
                    continue
                try:
                    project_id = int(raw_id)
                except ValueError:
                    logger.warning(
                        "Bỏ qua project_id migration demo không hợp lệ: %r", raw_id
                    )
                    continue
                if project_id > 0:
                    legacy_demo_project_ids.add(project_id)

            for project_id in sorted(legacy_demo_project_ids):
                migration_key = f"legacy_demo_session_expansion_v1:{project_id}"
                already_applied = connection.exec_driver_sql(
                    "SELECT 1 FROM app_data_migrations WHERE migration_key=%s",
                    (migration_key,),
                ).scalar()
                if already_applied:
                    continue

                legacy_project = (
                    connection.exec_driver_sql(
                        "SELECT id, periods_per_session, blocked_slots_json FROM projects "
                        "WHERE id=%s AND sessions=1",
                        (project_id,),
                    )
                    .mappings()
                    .first()
                )
                if legacy_project is None:
                    logger.warning(
                        "Không migrate project %s: không tồn tại hoặc sessions không còn là 1.",
                        project_id,
                    )
                    continue

                periods_per_session = int(legacy_project["periods_per_session"])

                def remap_json_slots(raw_value):
                    return json.dumps(
                        remap_slots_for_session_expansion(
                            parse_integer_set(raw_value),
                            old_sessions=1,
                            new_sessions=2,
                            periods_per_session=periods_per_session,
                        )
                    )

                connection.exec_driver_sql(
                    "UPDATE projects SET blocked_slots_json=%s WHERE id=%s",
                    (
                        remap_json_slots(legacy_project["blocked_slots_json"]),
                        project_id,
                    ),
                )

                for table_name in ("lessons", "fixed_lessons"):
                    if table_name not in inspector.get_table_names():
                        continue
                    rows = (
                        connection.exec_driver_sql(
                            f"SELECT id, slot FROM {table_name} WHERE project_id=%s",
                            (project_id,),
                        )
                        .mappings()
                        .all()
                    )
                    for row in rows:
                        mapped_slot = remap_slot_for_session_expansion(
                            row["slot"],
                            old_sessions=1,
                            new_sessions=2,
                            periods_per_session=periods_per_session,
                        )
                        connection.exec_driver_sql(
                            f"UPDATE {table_name} SET slot=%s WHERE id=%s",
                            (mapped_slot, row["id"]),
                        )

                json_slot_columns = {
                    "teachers": ("unavailable_json",),
                    "classes": ("unavailable_json",),
                    "teacher_preferences": ("preferred_json", "unavailable_json"),
                }
                for table_name, column_names in json_slot_columns.items():
                    if table_name not in inspector.get_table_names():
                        continue
                    selected_columns = ", ".join(("id", *column_names))
                    rows = (
                        connection.exec_driver_sql(
                            f"SELECT {selected_columns} FROM {table_name} WHERE project_id=%s",
                            (project_id,),
                        )
                        .mappings()
                        .all()
                    )
                    for row in rows:
                        assignments_sql = ", ".join(
                            f"{column}=%s" for column in column_names
                        )
                        values = tuple(
                            remap_json_slots(row[column]) for column in column_names
                        )
                        connection.exec_driver_sql(
                            f"UPDATE {table_name} SET {assignments_sql} WHERE id=%s",
                            (*values, row["id"]),
                        )

                connection.exec_driver_sql(
                    "UPDATE projects SET sessions=2 WHERE id=%s",
                    (project_id,),
                )
                connection.exec_driver_sql(
                    "INSERT INTO app_data_migrations (migration_key, applied_at) "
                    "VALUES (%s, %s)",
                    (migration_key, datetime.now(timezone.utc).isoformat()),
                )


def acquire_database_bootstrap_lock(lock_connection):
    deadline = time.monotonic() + DATABASE_BOOTSTRAP_LOCK_TIMEOUT_SECONDS
    while True:
        acquired = bool(
            lock_connection.exec_driver_sql(
                "SELECT pg_try_advisory_lock(%s)",
                (DATABASE_BOOTSTRAP_LOCK_KEY,),
            ).scalar()
        )
        if acquired:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(
                "Không thể lấy khóa khởi tạo database trong thời gian cho phép."
            )
        time.sleep(min(0.25, remaining))


def run_database_bootstrap_step(callback):
    """Tuần tự hóa các bước DDL/bootstrap giữa nhiều process cùng dùng một PostgreSQL."""
    with engine.connect() as lock_connection:
        acquire_database_bootstrap_lock(lock_connection)
        try:
            return callback()
        finally:
            try:
                lock_connection.exec_driver_sql(
                    "SELECT pg_advisory_unlock(%s)",
                    (DATABASE_BOOTSTRAP_LOCK_KEY,),
                )
            except Exception:
                pass


def initialize_schema():
    with engine.begin() as schema_connection:
        schema_connection.exec_driver_sql(
            f"SET LOCAL lock_timeout = '{DATABASE_DDL_LOCK_TIMEOUT_SECONDS}s'"
        )
        schema_connection.exec_driver_sql(
            f"SET LOCAL statement_timeout = '{DATABASE_STATEMENT_TIMEOUT_SECONDS}s'"
        )
        Base.metadata.create_all(schema_connection)
    migrate_schema()


class Passwords:
    @staticmethod
    def hash(password: str) -> str:
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), 200_000
        ).hex()
        return f"pbkdf2_sha256${salt}${digest}"

    @staticmethod
    def verify(password: str, encoded: str) -> bool:
        try:
            algo, salt, digest = encoded.split("$", 2)
            if algo != "pbkdf2_sha256":
                return False
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), salt.encode(), 200_000
            ).hex()
            return hmac.compare_digest(actual, digest)
        except Exception:
            return False


pwd = Passwords()
signer = URLSafeTimedSerializer(SECRET_KEY, salt="session")
reset_signer = URLSafeTimedSerializer(SECRET_KEY, salt="password-reset")
captcha_signer = URLSafeTimedSerializer(SECRET_KEY, salt="forgot-password-captcha")
registration_signer = URLSafeTimedSerializer(
    SECRET_KEY, salt="registration-verification"
)
email_change_signer = URLSafeTimedSerializer(
    SECRET_KEY, salt="email-change-confirmation"
)
email_change_otp_signer = URLSafeTimedSerializer(
    SECRET_KEY, salt="email-change-verification"
)

app = FastAPI(title="Teacher Timetable")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/api/server-time")
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


class RealtimeConnectionManager:
    """Realtime registry shared across Uvicorn workers through PostgreSQL."""

    CHANNEL = "smart_tkb_realtime_v1"
    PRESENCE_TTL_SECONDS = 180
    PRESENCE_LOCK_BASE = 73120270000
    EVENT_TTL_SECONDS = 24 * 60 * 60
    SESSION_CHECK_INTERVAL_SECONDS = 15

    def __init__(self):
        self._lock = threading.RLock()
        self._connections: dict[int, dict[str, WebSocket]] = defaultdict(dict)
        self._instance_id = secrets.token_hex(12)
        self._listener_started = False
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._psycopg_dsn = DATABASE_URL.replace(
            "postgresql+psycopg://", "postgresql://", 1
        )

    def _presence_cutoff(self) -> str:
        return (
            datetime.now(timezone.utc)
            - timedelta(seconds=self.PRESENCE_TTL_SECONDS)
        ).isoformat(timespec="seconds")

    def _lock_user_presence(self, db: Session, user_id: int) -> None:
        db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": self.PRESENCE_LOCK_BASE + int(user_id)},
        )

    def _cleanup_stale_presence(self, db: Session) -> None:
        db.execute(
            delete(RealtimeConnection).where(
                RealtimeConnection.updated_at < self._presence_cutoff()
            )
        )

    def _ensure_listener(self, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self._event_loop = loop
            if self._listener_started:
                return
            self._listener_started = True
        threading.Thread(
            target=self._listen_for_remote_events,
            name=f"realtime-listener-{self._instance_id[:8]}",
            daemon=True,
        ).start()

    def _listen_for_remote_events(self) -> None:
        while True:
            try:
                with psycopg.connect(self._psycopg_dsn, autocommit=True) as conn:
                    conn.execute(f"LISTEN {self.CHANNEL}")
                    for notification in conn.notifies():
                        try:
                            envelope = self._notification_envelope(notification.payload)
                        except (TypeError, ValueError, json.JSONDecodeError):
                            continue
                        if not envelope or envelope.get("source") == self._instance_id:
                            continue
                        payload = envelope.get("payload")
                        if not isinstance(payload, dict):
                            continue
                        exclude_user_id = envelope.get("exclude_user_id")
                        only_raw = envelope.get("only_user_ids")
                        only_user_ids = (
                            {int(value) for value in only_raw}
                            if isinstance(only_raw, list)
                            else None
                        )
                        with self._lock:
                            loop = self._event_loop
                        if loop is None or loop.is_closed():
                            continue
                        asyncio.run_coroutine_threadsafe(
                            self._broadcast_local(
                                payload,
                                exclude_user_id=(
                                    int(exclude_user_id)
                                    if exclude_user_id is not None
                                    else None
                                ),
                                only_user_ids=only_user_ids,
                            ),
                            loop,
                        )
            except Exception:
                logger.exception("PostgreSQL realtime listener stopped; reconnecting.")
                time.sleep(2)

    def _notification_envelope(self, raw: str) -> dict | None:
        notice = json.loads(raw)
        if not isinstance(notice, dict):
            return None
        if notice.get("source") == self._instance_id:
            return None
        event_id = notice.get("event_id")
        if event_id is None:
            # Accept notifications sent by an older worker during restart.
            return notice
        if not isinstance(event_id, str) or len(event_id) > 64:
            return None
        with SessionLocal() as db:
            event = db.get(RealtimeEvent, event_id)
            if event is None or event.expires_at <= int(time.time()):
                return None
            envelope = json.loads(event.envelope_json)
        return envelope if isinstance(envelope, dict) else None

    def _publish_sync(
        self,
        payload: dict,
        exclude_user_id: int | None,
        only_user_ids: set[int] | None,
    ) -> None:
        if only_user_ids is not None and not only_user_ids:
            return
        now = int(time.time())
        event_id = secrets.token_hex(16)
        envelope = json.dumps(
            {
                "source": self._instance_id,
                "payload": payload,
                "exclude_user_id": exclude_user_id,
                "only_user_ids": (
                    sorted(int(uid) for uid in only_user_ids)
                    if only_user_ids is not None else None
                ),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        # Insert and notify in one transaction: another worker must never see
        # a notification before the complete event has been committed.
        with engine.begin() as connection:
            connection.execute(
                delete(RealtimeEvent).where(RealtimeEvent.expires_at <= now)
            )
            connection.execute(
                RealtimeEvent.__table__.insert().values(
                    id=event_id,
                    envelope_json=envelope,
                    expires_at=now + self.EVENT_TTL_SECONDS,
                )
            )
            connection.exec_driver_sql(
                "SELECT pg_notify(%s, %s)",
                (self.CHANNEL, json.dumps({"source": self._instance_id, "event_id": event_id})),
            )

    def add(self, user_id: int, connection_id: str, websocket: WebSocket) -> bool:
        try:
            self._ensure_listener(asyncio.get_running_loop())
        except RuntimeError:
            pass
        with self._lock:
            self._connections[user_id][connection_id] = websocket

        now = _utc_now_iso()
        db = SessionLocal()
        try:
            self._lock_user_presence(db, user_id)
            self._cleanup_stale_presence(db)
            was_offline = db.scalar(
                select(RealtimeConnection.connection_id)
                .where(
                    RealtimeConnection.user_id == user_id,
                    RealtimeConnection.updated_at >= self._presence_cutoff(),
                )
                .limit(1)
            ) is None
            db.merge(
                RealtimeConnection(
                    connection_id=connection_id,
                    user_id=user_id,
                    instance_id=self._instance_id,
                    updated_at=now,
                )
            )
            db.commit()
            return was_offline
        except Exception:
            db.rollback()
            logger.exception("Could not register shared realtime presence.")
            with self._lock:
                return len(self._connections.get(user_id, {})) == 1
        finally:
            db.close()

    def touch(self, user_id: int, connection_id: str) -> None:
        db = SessionLocal()
        try:
            row = db.get(RealtimeConnection, connection_id)
            if row and row.user_id == user_id and row.instance_id == self._instance_id:
                row.updated_at = _utc_now_iso()
                db.commit()
        except Exception:
            db.rollback()
            logger.exception("Could not refresh shared realtime presence.")
        finally:
            db.close()

    def remove(self, user_id: int, connection_id: str) -> bool:
        with self._lock:
            sockets = self._connections.get(user_id)
            if sockets:
                sockets.pop(connection_id, None)
                if not sockets:
                    self._connections.pop(user_id, None)

        db = SessionLocal()
        try:
            self._lock_user_presence(db, user_id)
            row = db.get(RealtimeConnection, connection_id)
            if row and row.user_id == user_id and row.instance_id == self._instance_id:
                db.delete(row)
            self._cleanup_stale_presence(db)
            still_online = db.scalar(
                select(RealtimeConnection.connection_id)
                .where(
                    RealtimeConnection.user_id == user_id,
                    RealtimeConnection.updated_at >= self._presence_cutoff(),
                )
                .limit(1)
            ) is not None
            db.commit()
            return not still_online
        except Exception:
            db.rollback()
            logger.exception("Could not remove shared realtime presence.")
            return False
        finally:
            db.close()

    def is_online(self, user_id: int) -> bool:
        return bool(self.online_user_ids_for({user_id}))

    def online_user_ids(self) -> list[int]:
        db = SessionLocal()
        try:
            return sorted(
                set(
                    db.scalars(
                        select(RealtimeConnection.user_id)
                        .where(RealtimeConnection.updated_at >= self._presence_cutoff())
                        .distinct()
                    ).all()
                )
            )
        finally:
            db.close()

    def online_count(self) -> int:
        return len(self.online_user_ids())

    def online_user_ids_for(self, allowed_user_ids: set[int]) -> list[int]:
        if not allowed_user_ids:
            return []
        db = SessionLocal()
        try:
            return sorted(
                set(
                    db.scalars(
                        select(RealtimeConnection.user_id)
                        .where(
                            RealtimeConnection.updated_at >= self._presence_cutoff(),
                            RealtimeConnection.user_id.in_(allowed_user_ids),
                        )
                        .distinct()
                    ).all()
                )
            )
        finally:
            db.close()

    def online_count_for(self, allowed_user_ids: set[int]) -> int:
        return len(self.online_user_ids_for(allowed_user_ids))

    async def _broadcast_local(
        self,
        payload: dict,
        exclude_user_id: int | None = None,
        only_user_ids: set[int] | None = None,
    ) -> None:
        with self._lock:
            targets = [
                (uid, cid, ws)
                for uid, sockets in self._connections.items()
                if (exclude_user_id is None or uid != exclude_user_id)
                and (only_user_ids is None or uid in only_user_ids)
                for cid, ws in sockets.items()
            ]
        dead: list[tuple[int, str]] = []
        if not targets:
            return
        valid_connections = await asyncio.to_thread(valid_realtime_connections, targets)
        for uid, cid, ws in targets:
            if cid not in valid_connections:
                # Let realtime_socket's finally block remove presence and
                # announce offline, rather than removing it twice here.
                try:
                    await ws.close(code=4401)
                except Exception:
                    pass
                continue
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append((uid, cid))
        for uid, cid in dead:
            self.remove(uid, cid)

    async def broadcast(
        self,
        payload: dict,
        exclude_user_id: int | None = None,
        only_user_ids: set[int] | None = None,
    ) -> None:
        await self._broadcast_local(payload, exclude_user_id, only_user_ids)
        try:
            await asyncio.to_thread(
                self._publish_sync, payload, exclude_user_id, only_user_ids
            )
        except Exception:
            logger.exception("Could not publish realtime event through PostgreSQL.")


realtime_manager = RealtimeConnectionManager()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def touch_user_last_seen(user_id: int, min_interval_seconds: int = 0) -> str:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="seconds")
    db = SessionLocal()
    try:
        account = db.get(User, user_id)
        if not account:
            return now_iso
        if min_interval_seconds > 0:
            previous = _parse_iso_datetime(account.last_seen)
            if previous is not None and (now - previous).total_seconds() < min_interval_seconds:
                return account.last_seen or now_iso
        account.last_seen = now_iso
        db.commit()
        return now_iso
    finally:
        db.close()


def valid_realtime_connections(targets: list[tuple[int, str, WebSocket]]) -> set[str]:
    """Check cookie expiry and current account versions before every broadcast.

    Cache accounts only within this call so a password change on any worker
    takes effect on the next delivery, including receive-only connections.
    """
    valid: set[str] = set()
    accounts: dict[int, User | None] = {}
    with SessionLocal() as db:
        for user_id, connection_id, websocket in targets:
            raw = websocket.cookies.get("session")
            if not raw:
                continue
            try:
                data = signer.loads(raw, max_age=SESSION_TTL_SECONDS)
                if int(data["uid"]) != user_id:
                    continue
                if user_id not in accounts:
                    accounts[user_id] = db.get(User, user_id)
                account = accounts[user_id]
                if account and int(data.get("sv", -1)) == account.session_version:
                    valid.add(connection_id)
            except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
                continue
    return valid


def websocket_session_user(websocket: WebSocket) -> User | None:
    raw = websocket.cookies.get("session")
    if not raw:
        return None
    db = SessionLocal()
    try:
        data = signer.loads(raw, max_age=SESSION_TTL_SECONDS)
        account = db.get(User, int(data["uid"]))
        if not account or int(data.get("sv", -1)) != account.session_version:
            return None
        return account
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None
    finally:
        db.close()


def school_chat_user_ids(db: Session, school_id: int) -> set[int]:
    member_ids = set(
        db.scalars(
            select(UserSchool.user_id).where(UserSchool.school_id == school_id)
        ).all()
    )
    member_ids.update(
        db.scalars(select(User.id).where(User.role == "super_admin")).all()
    )
    return member_ids


def presence_visible_user_ids(db: Session, viewer: User) -> set[int]:
    """Users whose online state may be exposed to this viewer."""
    if is_super_admin(viewer):
        return set(db.scalars(select(User.id)).all())

    visible = {viewer.id}
    for school_id in user_school_ids(viewer, db):
        visible.update(school_chat_user_ids(db, school_id))
    # Super admins may manage school-less accounts, but ordinary users must not
    # receive presence information from unrelated schools.
    visible.update(db.scalars(select(User.id).where(User.role == "super_admin")).all())
    return visible


def presence_recipients_for_user(db: Session, subject: User) -> set[int]:
    """Users allowed to receive a generic presence event for subject."""
    if is_super_admin(subject):
        return set(db.scalars(select(User.id)).all())

    recipients = set(
        db.scalars(select(User.id).where(User.role == "super_admin")).all()
    )
    for school_id in user_school_ids(subject, db):
        recipients.update(school_chat_user_ids(db, school_id))
    recipients.add(subject.id)
    return recipients


async def broadcast_school_presence(user: User, online: bool, last_seen: str) -> None:
    db = SessionLocal()
    try:
        school_ids = user_school_ids(user, db)
        for school_id in school_ids:
            recipients = school_chat_user_ids(db, school_id)
            await realtime_manager.broadcast(
                {
                    "type": "school_presence",
                    "school_id": school_id,
                    "user_id": user.id,
                    "online": online,
                    "last_seen": last_seen,
                    "online_count": realtime_manager.online_count_for(recipients),
                },
                only_user_ids=recipients,
            )
    finally:
        db.close()


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


def _captcha_svg_data_uri(kind: str, variant: int = 0) -> str:
    """Return a small self-contained SVG used by the visual captcha."""
    accents = [
        ("#e0f2fe", "#38bdf8", "#0f172a"),
        ("#ede9fe", "#8b5cf6", "#1e1b4b"),
        ("#dcfce7", "#22c55e", "#14532d"),
        ("#ffedd5", "#fb923c", "#7c2d12"),
        ("#fce7f3", "#ec4899", "#831843"),
    ]
    bg, accent, ink = accents[variant % len(accents)]
    drawings = {
        "tree": f'''<rect x="78" y="58" width="24" height="43" rx="5" fill="#8b5a2b"/>
<circle cx="90" cy="45" r="32" fill="{accent}"/><circle cx="66" cy="56" r="21" fill="{accent}"/><circle cx="113" cy="57" r="22" fill="{accent}"/>''',
        "car": f'''<path d="M42 70h97l-9-27c-2-7-8-11-15-11H70c-7 0-13 4-16 11L42 70Z" fill="{accent}"/>
<rect x="31" y="65" width="118" height="31" rx="13" fill="{accent}"/><circle cx="58" cy="96" r="13" fill="{ink}"/><circle cx="124" cy="96" r="13" fill="{ink}"/><path d="M66 42h43l7 21H58l8-21Z" fill="#fff" opacity=".82"/>''',
        "cloud": f'''<circle cx="72" cy="64" r="26" fill="{accent}"/><circle cx="101" cy="48" r="34" fill="{accent}"/><circle cx="128" cy="68" r="23" fill="{accent}"/><rect x="51" y="63" width="96" height="36" rx="18" fill="{accent}"/>''',
        "house": f'''<path d="M37 58 90 20l53 38v47H37V58Z" fill="{accent}"/><path d="M28 61 90 14l62 47" fill="none" stroke="{ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/><rect x="76" y="70" width="28" height="35" rx="3" fill="#fff" opacity=".86"/><rect x="48" y="66" width="21" height="20" rx="3" fill="#fff" opacity=".76"/>''',
        "star": f'''<path d="m90 15 17 34 38 5-28 27 7 38-34-18-34 18 7-38-28-27 38-5 17-34Z" fill="{accent}" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>''',
        "flower": f'''<circle cx="90" cy="55" r="15" fill="#facc15"/><circle cx="90" cy="29" r="21" fill="{accent}"/><circle cx="116" cy="51" r="21" fill="{accent}"/><circle cx="106" cy="80" r="21" fill="{accent}"/><circle cx="74" cy="80" r="21" fill="{accent}"/><circle cx="64" cy="51" r="21" fill="{accent}"/><path d="M90 93v24" stroke="#16a34a" stroke-width="9" stroke-linecap="round"/>''',
    }
    drawing = drawings[kind]
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="180" height="120" viewBox="0 0 180 120">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{bg}"/><stop offset="1" stop-color="#ffffff"/></linearGradient></defs>
<rect width="180" height="120" rx="18" fill="url(#g)"/><circle cx="18" cy="18" r="7" fill="{accent}" opacity=".24"/><circle cx="160" cy="98" r="12" fill="{accent}" opacity=".18"/>{drawing}</svg>'''
    return "data:image/svg+xml;charset=UTF-8," + quote(svg, safe="")


def _captcha_puzzle_piece_data_uris() -> list[str]:
    """Vẽ ảnh raster rồi cắt thật thành 4 mảnh; client không nhận tọa độ gốc."""
    width, height = 360, 240
    rng = random.SystemRandom()
    palette = rng.choice(
        [
            ((219, 234, 254), (147, 197, 253), (34, 197, 94)),
            ((252, 231, 243), (196, 181, 253), (22, 163, 74)),
            ((220, 252, 231), (186, 230, 253), (16, 185, 129)),
        ]
    )
    sky_top, sky_bottom, grass = palette
    image = Image.new("RGB", (width, height), sky_top)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(int(a + (b - a) * ratio) for a, b in zip(sky_top, sky_bottom))
        draw.line((0, y, width, y), fill=color)

    sun_x = rng.randint(260, 310)
    sun_y = rng.randint(38, 62)
    draw.ellipse((sun_x - 28, sun_y - 28, sun_x + 28, sun_y + 28), fill=(250, 204, 21))
    cloud_x = rng.randint(62, 108)
    cloud_y = rng.randint(36, 56)
    for dx, dy, radius in ((-28, 8, 18), (0, 0, 25), (28, 10, 17)):
        draw.ellipse(
            (
                cloud_x + dx - radius,
                cloud_y + dy - radius,
                cloud_x + dx + radius,
                cloud_y + dy + radius,
            ),
            fill=(248, 250, 252),
        )

    draw.polygon(
        [
            (0, 176),
            (82, 92),
            (141, 151),
            (203, 61),
            (295, 171),
            (360, 108),
            (360, 240),
            (0, 240),
        ],
        fill=(100, 116, 139),
    )
    draw.polygon(
        [
            (0, 187),
            (82, 121),
            (143, 179),
            (203, 93),
            (293, 191),
            (360, 135),
            (360, 240),
            (0, 240),
        ],
        fill=grass,
    )

    house_x = rng.randint(76, 105)
    draw.polygon(
        [(house_x - 56, 184), (house_x, 139), (house_x + 58, 184)], fill=(124, 45, 18)
    )
    draw.rectangle((house_x - 48, 184, house_x + 48, 239), fill=(251, 146, 60))
    draw.rectangle((house_x - 13, 200, house_x + 13, 239), fill=(255, 247, 237))
    draw.rectangle((house_x + 22, 195, house_x + 39, 213), fill=(224, 242, 254))

    tree_x = rng.randint(270, 310)
    draw.rounded_rectangle(
        (tree_x - 8, 163, tree_x + 8, 229), radius=5, fill=(146, 64, 14)
    )
    for dx, dy, radius, color in (
        (0, -18, 38, (21, 128, 61)),
        (-28, -5, 27, (22, 163, 74)),
        (28, -4, 28, (34, 197, 94)),
    ):
        draw.ellipse(
            (
                tree_x + dx - radius,
                163 + dy - radius,
                tree_x + dx + radius,
                163 + dy + radius,
            ),
            fill=color,
        )

    for _ in range(18):
        x = rng.randint(8, width - 8)
        y = rng.randint(8, height - 8)
        r = rng.randint(2, 5)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255))

    pieces: list[str] = []
    for top in (0, height // 2):
        for left in (0, width // 2):
            crop = image.crop((left, top, left + width // 2, top + height // 2))
            buffer = io.BytesIO()
            crop.save(buffer, format="PNG", optimize=True)
            pieces.append(
                "data:image/png;base64,"
                + base64.b64encode(buffer.getvalue()).decode("ascii")
            )
    return pieces


def new_captcha(purpose: str = "password_reset") -> tuple[dict, str]:
    kind = "images" if secrets.randbelow(100) < 65 else "puzzle"
    issued_at = int(datetime.now(timezone.utc).timestamp())
    nonce = secrets.token_urlsafe(18)

    if kind == "images":
        labels = {
            "tree": "cây",
            "car": "ô tô",
            "cloud": "đám mây",
            "house": "ngôi nhà",
            "star": "ngôi sao",
            "flower": "bông hoa",
        }
        categories = list(labels)
        target = secrets.choice(categories)
        system_random = random.SystemRandom()
        distractors = [item for item in categories if item != target]
        tile_kinds = [target, target] + system_random.sample(distractors, 4)
        system_random.shuffle(tile_kinds)
        tiles = []
        correct_ids = []
        for index, tile_kind in enumerate(tile_kinds):
            tile_id = secrets.token_urlsafe(6)
            if tile_kind == target:
                correct_ids.append(tile_id)
            tiles.append(
                {
                    "id": tile_id,
                    "src": _captcha_svg_data_uri(tile_kind, secrets.randbelow(5)),
                    "alt": f"Hình xác minh {index + 1}",
                }
            )
        expected = ",".join(sorted(correct_ids))
        challenge = {
            "kind": "images",
            "prompt": f"Chọn tất cả hình có {labels[target]}",
            "tiles": tiles,
            "required_count": len(correct_ids),
        }
    else:
        piece_images = _captcha_puzzle_piece_data_uris()
        pieces = []
        correct_ids = []
        for index, piece_image in enumerate(piece_images):
            piece_id = secrets.token_urlsafe(6)
            correct_ids.append(piece_id)
            pieces.append({"id": piece_id, "src": piece_image})
        random.SystemRandom().shuffle(pieces)
        while [piece["id"] for piece in pieces] == correct_ids:
            random.SystemRandom().shuffle(pieces)
        expected = ",".join(correct_ids)
        challenge = {
            "kind": "puzzle",
            "prompt": "Ghép 4 mảnh thành một bức tranh hoàn chỉnh",
            "pieces": pieces,
        }

    answer_hash = hmac.new(
        SECRET_KEY.encode(),
        f"captcha:{purpose}:{nonce}:{expected}".encode(),
        hashlib.sha256,
    ).hexdigest()
    token = captcha_signer.dumps(
        {
            "answer_hash": answer_hash,
            "purpose": purpose,
            "issued_at": issued_at,
            "nonce": nonce,
            "kind": kind,
        }
    )
    return challenge, token


def _consume_captcha_nonce(nonce: str, purpose: str, now_epoch: int) -> bool:
    nonce_hash = hashlib.sha256(nonce.encode()).hexdigest()
    with engine.begin() as connection:
        inserted = connection.exec_driver_sql(
            "INSERT INTO captcha_uses (nonce_hash, purpose, used_at) VALUES (%s, %s, %s) "
            "ON CONFLICT (nonce_hash) DO NOTHING RETURNING nonce_hash",
            (nonce_hash, purpose, now_epoch),
        ).scalar()
        if secrets.randbelow(100) < 5:
            connection.exec_driver_sql(
                "DELETE FROM captcha_uses WHERE used_at < %s",
                (now_epoch - 15 * 60,),
            )
    return inserted is not None


def captcha_is_valid(token: str, answer: str, purpose: str = "password_reset") -> bool:
    try:
        data = captcha_signer.loads(token, max_age=5 * 60)
        now_epoch = int(datetime.now(timezone.utc).timestamp())
        age = now_epoch - int(data["issued_at"])
        submitted = answer.strip()
        if data.get("kind") == "images":
            submitted = ",".join(sorted(filter(None, submitted.split(","))))
        elif data.get("kind") == "puzzle":
            submitted = ",".join(filter(None, submitted.split(",")))
        else:
            return False
        if data["purpose"] != purpose or not 2 <= age <= 5 * 60:
            return False
        submitted_hash = hmac.new(
            SECRET_KEY.encode(),
            f"captcha:{purpose}:{data['nonce']}:{submitted}".encode(),
            hashlib.sha256,
        ).hexdigest()
        if not _consume_captcha_nonce(str(data["nonce"]), purpose, now_epoch):
            return False
        return hmac.compare_digest(str(data["answer_hash"]), submitted_hash)
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return False


def _rate_limit_identity(value: str) -> str:
    return hmac.new(SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()[
        :48
    ]


def client_rate_limit_key(request: Request) -> str:
    host = request.client.host if request.client and request.client.host else "unknown"
    return _rate_limit_identity(host.strip().lower())


def rate_limit_exceeded(
    scope: str, identity: str, *, limit: int, window_seconds: int
) -> bool:
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    cutoff = now_epoch - window_seconds
    bucket_key = f"{scope}:{_rate_limit_identity(identity.strip().lower())}"
    with engine.begin() as connection:
        row = connection.exec_driver_sql(
            "INSERT INTO rate_limit_buckets (bucket_key, window_started_at, count, touched_at) "
            "VALUES (%s, %s, 1, %s) "
            "ON CONFLICT (bucket_key) DO UPDATE SET "
            "count=CASE WHEN rate_limit_buckets.window_started_at < %s THEN 1 ELSE rate_limit_buckets.count + 1 END, "
            "window_started_at=CASE WHEN rate_limit_buckets.window_started_at < %s THEN %s ELSE rate_limit_buckets.window_started_at END, "
            "touched_at=%s "
            "RETURNING count",
            (bucket_key, now_epoch, now_epoch, cutoff, cutoff, now_epoch, now_epoch),
        ).scalar_one()
        if secrets.randbelow(100) < 3:
            connection.exec_driver_sql(
                "DELETE FROM rate_limit_buckets WHERE touched_at < %s",
                (now_epoch - 24 * 60 * 60,),
            )
    return int(row) > limit


def rate_limit_blocked(
    scope: str, identity: str, *, limit: int, window_seconds: int
) -> bool:
    """Kiểm tra bucket hiện tại mà không tăng bộ đếm."""
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    cutoff = now_epoch - window_seconds
    bucket_key = f"{scope}:{_rate_limit_identity(identity.strip().lower())}"
    with engine.begin() as connection:
        row = (
            connection.exec_driver_sql(
                "SELECT window_started_at, count FROM rate_limit_buckets WHERE bucket_key=%s",
                (bucket_key,),
            )
            .mappings()
            .first()
        )
    if not row or int(row["window_started_at"]) < cutoff:
        return False
    return int(row["count"]) >= limit


def clear_rate_limit_bucket(scope: str, identity: str) -> None:
    bucket_key = f"{scope}:{_rate_limit_identity(identity.strip().lower())}"
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DELETE FROM rate_limit_buckets WHERE bucket_key=%s",
            (bucket_key,),
        )


def send_email_message(recipient: str, subject: str, body: str) -> bool:
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    if not smtp_host:
        return False

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "no-reply@smart-tkb.local").strip()
    use_ssl = os.getenv("SMTP_SSL", "false").strip().lower() in {"1", "true", "yes"}
    use_starttls = os.getenv("SMTP_STARTTLS", "true").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    timeout = max(5, int(os.getenv("SMTP_TIMEOUT_SECONDS", "30")))

    # Gmail SMTP always requires authentication. A missing credential should fail loudly
    # in the server log instead of silently pretending that the message was sent.
    if smtp_host.lower() == "smtp.gmail.com" and (not smtp_user or not smtp_password):
        raise smtplib.SMTPAuthenticationError(
            535, b"Missing SMTP_USER or SMTP_PASSWORD"
        )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = smtp_from
    message["To"] = recipient
    message.set_content(body)

    smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with smtp_class(smtp_host, smtp_port, timeout=timeout) as client:
        client.ehlo()
        if not use_ssl and use_starttls:
            client.starttls()
            client.ehlo()
        if smtp_user:
            client.login(smtp_user, smtp_password)
        refused = client.send_message(message)
        if refused:
            logger.error("SMTP refused password-reset recipient(s): %s", list(refused))
            return False
    return True


def send_password_reset_email(recipient: str, reset_url: str) -> bool:
    return send_email_message(
        recipient,
        "Đặt lại mật khẩu Smart TKB",
        "Bạn vừa yêu cầu đặt lại mật khẩu Smart TKB.\n\n"
        f"Mở liên kết sau trong vòng 30 phút:\n{reset_url}\n\n"
        "Nếu bạn không yêu cầu, hãy bỏ qua email này.",
    )


def send_registration_otp_email(recipient: str, otp: str, teacher_name: str) -> bool:
    return send_email_message(
        recipient,
        "Mã xác nhận đăng ký Smart TKB",
        f"Mã OTP đăng ký tài khoản của bạn là: {otp}\n\n"
        f"Tên giáo viên: {teacher_name}\n"
        "Mã có hiệu lực trong 10 phút và chỉ dùng được một lần.\n\n"
        "Nếu bạn không thực hiện đăng ký này, hãy bỏ qua email.",
    )


def registration_otp_hash(email: str, otp: str) -> str:
    return hmac.new(
        SECRET_KEY.encode(), f"{email}:{otp}".encode(), hashlib.sha256
    ).hexdigest()


def send_email_change_otp_email(recipient: str, otp: str) -> bool:
    return send_email_message(
        recipient,
        "Mã xác nhận đổi email Smart TKB",
        f"Mã OTP xác nhận email mới của bạn là: {otp}\n\n"
        "Mã có hiệu lực trong 10 phút và chỉ dùng được một lần.\n\n"
        "Nếu bạn không yêu cầu thay đổi email, hãy bỏ qua thư này.",
    )


def email_change_otp_hash(user_id: int, email: str, otp: str) -> str:
    value = f"email-change:{user_id}:{email.lower().strip()}:{otp}"
    return hmac.new(SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def public_base_url(request: Request) -> str | None:
    if APP_BASE_URL:
        return APP_BASE_URL
    if development_reset_links_enabled(request):
        return str(request.base_url).rstrip("/")
    return None


def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def set_session_cookie(response, user: User):
    response.set_cookie(
        "session",
        signer.dumps({"uid": user.id, "sv": user.session_version}),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=APP_ENV == "production" or APP_BASE_URL.lower().startswith("https://"),
    )


def current_user(request: Request, db: Session = Depends(db_session)) -> User:
    raw = request.cookies.get("session")
    if not raw:
        raise HTTPException(401)
    try:
        data = signer.loads(raw, max_age=SESSION_TTL_SECONDS)
        user = db.get(User, int(data["uid"]))
        if not user or int(data.get("sv", -1)) != user.session_version:
            raise HTTPException(401)
        now = datetime.now(timezone.utc)
        previous = _parse_iso_datetime(user.last_seen)
        if previous is None or (now - previous).total_seconds() >= 60:
            user.last_seen = now.isoformat(timespec="seconds")
            db.commit()
        return user
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        raise HTTPException(401)


def is_admin(user: User) -> bool:
    return user.role in ADMIN_ROLES


def is_super_admin(user: User) -> bool:
    return user.role == "super_admin"


def user_greeting_name(user: User) -> str:
    # Lời chào dùng đúng họ tên/tên hiển thị lưu trong hồ sơ người dùng.
    # Không suy ra tên từ phần trước dấu @ của email vì đó chỉ là tên tài khoản.
    return (user.name or "").strip() or "Người dùng"


def user_school_ids(user: User, db: Session) -> set[int]:
    if is_super_admin(user):
        return set(db.scalars(select(School.id)).all())
    return set(
        db.scalars(
            select(UserSchool.school_id).where(UserSchool.user_id == user.id)
        ).all()
    )


def user_schools(user: User, db: Session) -> list[School]:
    if is_super_admin(user):
        return db.scalars(select(School).order_by(School.name.asc())).all()
    ids = user_school_ids(user, db)
    if not ids:
        return []
    return db.scalars(
        select(School).where(School.id.in_(ids)).order_by(School.name.asc())
    ).all()


def user_can_access_school(user: User, school_id: int | None, db: Session) -> bool:
    if is_super_admin(user):
        return True
    if school_id is None:
        return False
    return school_id in user_school_ids(user, db)


def ensure_school_for_name(db: Session, school_name: str) -> School:
    clean_name = bounded_text(school_name, "Tên trường", 200)
    school = db.scalar(select(School).where(School.name == clean_name))
    if school is None:
        school = School(name=clean_name)
        db.add(school)
        db.flush()
    return school


def get_project(pid: int, user: User, db: Session) -> Project:
    if not is_admin(user):
        raise HTTPException(403, "Chỉ quản trị viên được thực hiện thao tác này")
    p = db.get(Project, pid)
    if not p or not user_can_access_school(user, p.school_id, db):
        raise HTTPException(404, "Không tìm thấy bộ thời khóa biểu")
    return p


def chatbot_ui_context(project: Project | None) -> dict:
    return {
        "chatbot_project_id": project.id if project else None,
        "chatbot_project_name": project.name if project else "",
        "chatbot_enabled": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "chatbot_primary_model": os.getenv("GEMINI_MODEL", "gemini-3.7-flash").strip()
        or "gemini-3.7-flash",
    }


def chatbot_project_for_user(
    user: User, db: Session, preferred_id: int | None = None
) -> Project | None:
    if preferred_id is not None:
        if is_admin(user):
            return get_project(preferred_id, user, db)
        if user.role == "teacher":
            project = db.get(Project, preferred_id)
            if project and user_can_access_school(user, project.school_id, db):
                return project
            return None
        return None
    if is_admin(user) or user.role == "teacher":
        query = select(Project)
        if not is_super_admin(user):
            school_ids = user_school_ids(user, db)
            if not school_ids:
                return None
            query = query.where(Project.school_id.in_(school_ids))
        return db.scalar(query.order_by(Project.id.desc()).limit(1))
    return None


def chatbot_project_data_for_user(
    pid: int, user: User, db: Session
) -> tuple[Project, dict]:
    if is_admin(user):
        project = get_project(pid, user, db)
        return project, project_data(db, project)
    if user.role == "teacher":
        project = db.get(Project, pid)
        if not project or not user_can_access_school(user, project.school_id, db):
            raise HTTPException(404, "Không tìm thấy bộ thời khóa biểu")
        return project, public_project_data(db, project)
    raise HTTPException(
        403, "Tài khoản không có quyền sử dụng chatbot cho bộ thời khóa biểu này"
    )


def get_project_for_update(pid: int, user: User, db: Session) -> Project:
    """Khóa project đến hết transaction để tuần tự hóa mọi thay đổi lịch."""
    if not is_admin(user):
        raise HTTPException(403, "Chỉ quản trị viên được thực hiện thao tác này")
    query = select(Project).where(Project.id == pid)
    if not is_super_admin(user):
        school_ids = user_school_ids(user, db)
        if not school_ids:
            raise HTTPException(404, "Không tìm thấy bộ thời khóa biểu")
        query = query.where(Project.school_id.in_(school_ids))
    project = db.scalar(query.with_for_update())
    if not project:
        raise HTTPException(404, "Không tìm thấy bộ thời khóa biểu")
    return project


def admin_can_manage_account(
    admin: User, account: User, db: Session | None = None
) -> bool:
    if not is_admin(admin):
        return False
    if account.id == admin.id:
        return True
    if is_super_admin(admin):
        return account.role != "super_admin"
    if account.role != "teacher" or db is None:
        return False

    admin_school_ids = user_school_ids(admin, db)
    if not admin_school_ids:
        return False
    account_school_ids = set(
        db.scalars(
            select(UserSchool.school_id).where(UserSchool.user_id == account.id)
        ).all()
    )
    # Giáo viên chưa có trường có thể được một admin có trường nhận vào phạm vi
    # quản lý; giáo viên đã có trường chỉ hiện cho admin có ít nhất một trường chung.
    return not account_school_ids or bool(admin_school_ids & account_school_ids)


def development_reset_links_enabled(request: Request) -> bool:
    host = (request.url.hostname or "").lower()
    return APP_ENV == "development" and host in {"localhost", "127.0.0.1", "::1"}


def slot_meta(project: Project, slot: int):
    ppd = project.sessions * project.periods_per_session
    day = slot // ppd
    inside = slot % ppd
    session = inside // project.periods_per_session
    period = inside % project.periods_per_session
    return day, session, period


def all_slots(project: Project):
    return list(range(project.days * project.sessions * project.periods_per_session))


def parse_slots(text: str):
    return parse_integer_set(text)


BLOCK_MODES = {"free", "preferred_double", "required_double"}


def consecutive_groups(pattern: str, total_periods: int):
    """Đọc mẫu cụm cũ, chỉ dùng cho migration/tương thích dữ liệu cũ."""
    text = (pattern or "").strip()
    if not text:
        return [1] * total_periods
    try:
        groups = [int(value.strip()) for value in text.split(",") if value.strip()]
    except ValueError as exc:
        raise ValueError("Mẫu tiết liên tiếp cũ không hợp lệ.") from exc
    if not groups or any(value < 1 for value in groups) or sum(groups) != total_periods:
        raise ValueError("Mẫu tiết liên tiếp cũ không hợp lệ.")
    return groups


def normalized_block_mode(
    value: str, total_periods: int, subject: Subject, project: Project
):
    mode = (value or "free").strip().lower()
    aliases = {
        "prefer_double": "preferred_double",
        "preferred": "preferred_double",
        "required": "required_double",
        "double": "required_double",
    }
    mode = aliases.get(mode, mode)
    if mode not in BLOCK_MODES:
        raise ValueError("Chế độ xếp tiết không hợp lệ.")
    total_slots = project.days * project.sessions * project.periods_per_session
    if total_periods > total_slots:
        raise ValueError(
            f"Số tiết/tuần không được vượt quá {total_slots} ô của thời khóa biểu."
        )
    if mode in {"preferred_double", "required_double"} and total_periods >= 2:
        if subject.max_consecutive < 2:
            raise ValueError(
                f"Môn {subject.name} đang giới hạn tối đa {subject.max_consecutive} tiết liên tiếp; "
                "hãy tăng giới hạn lên ít nhất 2 trước khi chọn chế độ tiết đôi."
            )
        if project.periods_per_session < 2:
            raise ValueError("Mỗi buổi phải có ít nhất 2 tiết để dùng chế độ tiết đôi.")
    if mode == "required_double":
        groups = [2] * (total_periods // 2) + ([1] if total_periods % 2 else [])
        if not timetable_pattern_feasible(project, groups):
            raise ValueError(
                "Số cặp tiết bắt buộc không thể phân bố trong số ngày, buổi và tiết hiện có."
            )
    return mode


def assignment_requires_double(assignment: Assignment):
    return getattr(assignment, "block_mode", "free") == "required_double"


def assignment_prefers_double(assignment: Assignment):
    return getattr(assignment, "block_mode", "free") == "preferred_double"


def assignment_groups(assignment: Assignment):
    total = max(0, int(assignment.periods_per_week or 0))
    if assignment_requires_double(assignment):
        return [2] * (total // 2) + ([1] if total % 2 else [])
    return [1] * total


def required_double_hard_feasible(
    project: Project,
    teacher: Teacher,
    school_class: SchoolClass,
    total_periods: int,
    *,
    max_periods_day: int | None = None,
    teacher_unavailable_slots: set[int] | None = None,
    class_unavailable_slots: set[int] | None = None,
    project_blocked_slots: set[int] | None = None,
    max_consecutive: int | None = None,
) -> bool:
    """Kiểm tra sớm mẫu required_double chỉ với các ràng buộc cứng.

    Khác kiểm tra capacity theo tuần, hàm này chứng minh rằng số cặp 2 tiết
    thực sự có thể đặt vào các ô còn dùng được, không vượt giới hạn
    tiết/ngày và không tạo chuỗi môn dài hơn ``max_consecutive``. Các cặp
    vẫn được phép nằm sát nhau khi giới hạn liên tiếp của môn cho phép.
    """
    total = max(0, int(total_periods or 0))
    target_doubles = total // 2
    target_singles = total % 2
    if target_doubles == 0 and target_singles == 0:
        return True

    daily_limit = int(
        max_periods_day if max_periods_day is not None else teacher.max_periods_day
    )
    if target_doubles and daily_limit < 2:
        return False

    maximum = project.days * project.sessions * project.periods_per_session
    project_blocked = (
        set(project_blocked_slots)
        if project_blocked_slots is not None
        else set(
            valid_slots(project, parse_slots(project.blocked_slots_json), strict=False)
        )
    )
    teacher_blocked = (
        set(teacher_unavailable_slots)
        if teacher_unavailable_slots is not None
        else set(
            valid_slots(project, parse_slots(teacher.unavailable_json), strict=False)
        )
    )
    class_blocked = (
        set(class_unavailable_slots)
        if class_unavailable_slots is not None
        else set(
            valid_slots(
                project, parse_slots(school_class.unavailable_json), strict=False
            )
        )
    )
    blocked = {
        slot
        for slot in project_blocked | teacher_blocked | class_blocked
        if 0 <= slot < maximum
    }

    ppd = project.sessions * project.periods_per_session
    pps = project.periods_per_session
    max_run = max(1, int(max_consecutive if max_consecutive is not None else pps))
    if target_doubles and max_run < 2:
        return False

    def session_options(day: int, session: int):
        base = day * ppd + session * pps
        allowed = [base + period not in blocked for period in range(pps)]
        memo = {}

        def walk(period: int, current_run: int):
            if period >= pps:
                return {(0, 0)}
            key = (period, current_run)
            if key in memo:
                return memo[key]

            # Bỏ trống tiết hiện tại sẽ cắt chuỗi liên tiếp của môn.
            options = set(walk(period + 1, 0))
            if allowed[period] and current_run + 1 <= max_run:
                for doubles, singles in walk(period + 1, current_run + 1):
                    if singles < 1:
                        options.add((doubles, singles + 1))
            if (
                period + 1 < pps
                and allowed[period]
                and allowed[period + 1]
                and current_run + 2 <= max_run
            ):
                for doubles, singles in walk(period + 2, current_run + 2):
                    options.add((doubles + 1, singles))
            memo[key] = options
            return options

        return {
            (min(d, target_doubles), min(s, target_singles))
            for d, s in walk(0, 0)
            if d <= target_doubles and s <= target_singles
        }

    day_options = []
    for day in range(project.days):
        combined = {(0, 0)}
        for session in range(project.sessions):
            next_options = set()
            for left_d, left_s in combined:
                for right_d, right_s in session_options(day, session):
                    doubles = left_d + right_d
                    singles = left_s + right_s
                    if doubles <= target_doubles and singles <= target_singles:
                        next_options.add((doubles, singles))
            combined = next_options
        day_options.append({(d, s) for d, s in combined if 2 * d + s <= daily_limit})

    reachable = {(0, 0)}
    for options in day_options:
        next_reachable = set(reachable)
        for current_d, current_s in reachable:
            for add_d, add_s in options:
                doubles = current_d + add_d
                singles = current_s + add_s
                if doubles <= target_doubles and singles <= target_singles:
                    next_reachable.add((doubles, singles))
        reachable = next_reachable
    return (target_doubles, target_singles) in reachable


def ensure_required_double_hard_feasible(
    project: Project,
    teacher: Teacher,
    school_class: SchoolClass,
    subject: Subject,
    total_periods: int,
    mode: str,
    *,
    max_periods_day: int | None = None,
    teacher_unavailable_slots: set[int] | None = None,
    class_unavailable_slots: set[int] | None = None,
    project_blocked_slots: set[int] | None = None,
) -> None:
    if mode != "required_double":
        return
    daily_limit = int(
        max_periods_day if max_periods_day is not None else teacher.max_periods_day
    )
    if total_periods >= 2 and daily_limit < 2:
        raise HTTPException(
            409,
            f"Không thể dùng bắt buộc tiết đôi cho {school_class.name} – {subject.name}: "
            f"{teacher.name} chỉ được dạy tối đa {daily_limit} tiết/ngày. "
            "Cần ít nhất 2 tiết/ngày để xếp một cặp tiết.",
        )
    if not required_double_hard_feasible(
        project,
        teacher,
        school_class,
        total_periods,
        max_periods_day=max_periods_day,
        teacher_unavailable_slots=teacher_unavailable_slots,
        class_unavailable_slots=class_unavailable_slots,
        project_blocked_slots=project_blocked_slots,
        max_consecutive=subject.max_consecutive,
    ):
        raise HTTPException(
            409,
            f"Không thể xếp đủ các cặp tiết bắt buộc cho {school_class.name} – {subject.name} "
            f"với {teacher.name} theo tiết tránh, buổi/tiết khóa, giới hạn tiết/ngày "
            f"và tối đa {subject.max_consecutive} tiết liên tiếp của môn.",
        )


def assignment_generated_pattern(assignment: Assignment):
    return (
        ",".join(str(value) for value in assignment_groups(assignment))
        if assignment_requires_double(assignment)
        else ""
    )


def valid_slots(
    project: Project,
    slots: list[int] | set[int] | tuple[int, ...],
    *,
    strict: bool = True,
):
    """Chuẩn hóa slot; dữ liệu API sai phạm vi phải bị từ chối rõ ràng."""
    maximum = project.days * project.sessions * project.periods_per_session
    try:
        return normalize_slot_values(slots, maximum, strict=strict)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def bounded_int(value, default: int, minimum: int, maximum: int, label: str):
    raw = default if value in (None, "") else value
    if isinstance(raw, bool) or isinstance(raw, float) and not raw.is_integer():
        raise HTTPException(
            400, f"{label} phải là số nguyên từ {minimum} đến {maximum}"
        )
    try:
        parsed = int(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            400, f"{label} phải là số nguyên từ {minimum} đến {maximum}"
        ) from exc
    if not minimum <= parsed <= maximum:
        raise HTTPException(
            400, f"{label} phải nằm trong khoảng từ {minimum} đến {maximum}"
        )
    return parsed


def pattern_slots_match(
    project: Project, pattern: str, total_periods: int, slots: list[int] | set[int]
):
    """Kiểm tra các cụm tiết thực tế có đúng mẫu đã khai báo hay không."""
    try:
        expected = sorted(consecutive_groups(pattern, total_periods))
    except ValueError:
        return False
    if len(slots) != total_periods:
        return False
    ppd = project.sessions * project.periods_per_session
    groups = defaultdict(list)
    for slot in sorted(set(slots)):
        day = slot // ppd
        inside = slot % ppd
        session = inside // project.periods_per_session
        period = inside % project.periods_per_session
        groups[(day, session)].append(period)
    actual = []
    for periods in groups.values():
        run = 1
        for left, right in zip(periods, periods[1:]):
            if right == left + 1:
                run += 1
            else:
                actual.extend([2] * (run // 2))
                if run % 2:
                    actual.append(1)
                run = 1
        actual.extend([2] * (run // 2))
        if run % 2:
            actual.append(1)
    return sorted(actual) == expected


def assignment_run_groups(project: Project, slots: list[int] | set[int]):
    """Trả về các cụm liên tiếp theo đúng ranh giới ngày và buổi."""
    grouped = defaultdict(list)
    for slot in sorted(set(slots)):
        day, session, period = slot_meta(project, slot)
        grouped[(day, session)].append((period, slot))
    runs = []
    for values in grouped.values():
        current = [values[0]] if values else []
        for item in values[1:]:
            if item[0] == current[-1][0] + 1:
                current.append(item)
            else:
                runs.append(
                    {
                        "start": current[0][1],
                        "size": len(current),
                        "slots": [x[1] for x in current],
                    }
                )
                current = [item]
        if current:
            runs.append(
                {
                    "start": current[0][1],
                    "size": len(current),
                    "slots": [x[1] for x in current],
                }
            )
    return sorted(runs, key=lambda item: item["start"])


def required_double_slot_groups(project: Project, slots: list[int] | set[int]):
    """Partition occupied runs into adjacent required-double groups.

    A run of four periods becomes two pairs; a run of three becomes one pair
    plus one single. This keeps pin/remove behavior deterministic now that
    required-double groups may touch.
    """
    groups = []
    for run in assignment_run_groups(project, slots):
        values = list(run["slots"])
        for index in range(0, len(values), 2):
            chunk = values[index : index + 2]
            groups.append(
                {"start": chunk[0], "size": len(chunk), "slots": chunk}
            )
    return groups


def preferred_double_pair_count(project: Project, slots: list[int] | set[int]):
    """Đếm các cụm đúng 2 tiết cho chế độ ưu tiên tiết đôi.

    Cụm 3 hoặc 4 tiết liên tiếp không được tách ngầm thành các cặp ảo. Điều này
    giữ cách chấm điểm của solver đồng nhất với cách giao diện đánh dấu tiết đôi.
    """
    return sum(1 for run in assignment_run_groups(project, slots) if run["size"] == 2)


def _pack_pattern_groups_into_segments(
    group_sizes: list[int], segments: list[tuple[int, int]]
):
    """Xếp các cụm chưa neo vào những đoạn trống; các cụm được phép nằm sát nhau."""
    items = sorted((int(size) for size in group_sizes), reverse=True)
    if not items:
        return []
    usable = [(start, length) for start, length in segments if length > 0]
    capacities = [length for _start, length in usable]
    if sum(items) > sum(capacities):
        return None
    allocations = [[] for _segment in usable]
    failed = set()

    def search(index: int):
        if index == len(items):
            return True
        state = (index, tuple(sorted(capacities, reverse=True)))
        if state in failed:
            return False
        size = items[index]
        weight = size
        seen_capacities = set()
        for segment_index, capacity in enumerate(capacities):
            if capacity < weight or capacity in seen_capacities:
                continue
            seen_capacities.add(capacity)
            capacities[segment_index] -= weight
            allocations[segment_index].append(size)
            if search(index + 1):
                return True
            allocations[segment_index].pop()
            capacities[segment_index] += weight
        failed.add(state)
        return False

    if not search(0):
        return None
    placements = []
    for (segment_start, _length), sizes in zip(usable, allocations):
        cursor = segment_start
        for size in sizes:
            placements.append((size, cursor))
            cursor += size
    return placements


def _complete_pattern_placement(
    project: Project,
    expected: list[int],
    slots: list[int] | set[int],
    forced_placements: list[tuple[int, int]] | None = None,
):
    """Tìm một cách đặt đầy đủ các cụm, đồng thời chứa chính xác các tiết đã có."""
    values = list(slots)
    current = set(values)
    maximum = project.days * project.sessions * project.periods_per_session
    if len(values) != len(current) or any(
        slot < 0 or slot >= maximum for slot in current
    ):
        return None
    if len(current) > sum(expected) or any(
        size < 1 or size > project.periods_per_session for size in expected
    ):
        return None

    ppd = project.sessions * project.periods_per_session
    periods_per_session = project.periods_per_session
    starts_by_size = {}
    for size in set(expected):
        starts = []
        for day in range(project.days):
            for session in range(project.sessions):
                base = day * ppd + session * periods_per_session
                starts.extend(
                    base + period for period in range(periods_per_session - size + 1)
                )
        starts_by_size[size] = starts

    def interval(start: int, size: int):
        return set(range(start, start + size))

    def compatible(left_start: int, left_size: int, right_start: int, right_size: int):
        left_slots = interval(left_start, left_size)
        right_slots = interval(right_start, right_size)
        if left_slots.intersection(right_slots):
            return False
        return True

    def free_segments(selected: list[tuple[int, int, set[int]]]):
        forbidden = defaultdict(set)
        for size, start, _covered in selected:
            day, session, period = slot_meta(project, start)
            key = (day, session)
            forbidden[key].update(range(period, period + size))
        result = []
        for day in range(project.days):
            for session in range(project.sessions):
                blocked = forbidden[(day, session)]
                base = day * ppd + session * periods_per_session
                start = None
                for period in range(periods_per_session + 1):
                    is_free = period < periods_per_session and period not in blocked
                    if is_free and start is None:
                        start = period
                    elif not is_free and start is not None:
                        result.append((base + start, period - start))
                        start = None
        return result

    remaining = Counter(expected)
    selected = []
    forced_covered = set()
    for size, start in forced_placements or []:
        if remaining[size] <= 0 or start not in starts_by_size.get(size, []):
            return None
        covered = current.intersection(interval(start, size))
        if not covered or forced_covered.intersection(covered):
            return None
        if any(
            not compatible(start, size, other_start, other_size)
            for other_size, other_start, _ in selected
        ):
            return None
        remaining[size] -= 1
        selected.append((size, start, set(covered)))
        forced_covered.update(covered)
    failed = set()

    def search(uncovered: frozenset[int]):
        state = (
            tuple(sorted(uncovered)),
            tuple(sorted(remaining.items())),
            tuple(sorted((size, start) for size, start, _covered in selected)),
        )
        if state in failed:
            return None
        if not uncovered:
            rest = []
            for size, count in remaining.items():
                rest.extend([size] * count)
            packed = _pack_pattern_groups_into_segments(rest, free_segments(selected))
            if packed is None:
                failed.add(state)
                return None
            return [*selected, *[(size, start, set()) for size, start in packed]]

        target = min(uncovered)
        for size in sorted(
            (value for value, count in remaining.items() if count > 0), reverse=True
        ):
            for start in starts_by_size[size]:
                target_slots = interval(start, size)
                covered = current.intersection(target_slots)
                if target not in covered or not covered.issubset(uncovered):
                    continue
                if any(
                    not compatible(start, size, other_start, other_size)
                    for other_size, other_start, _ in selected
                ):
                    continue
                remaining[size] -= 1
                selected.append((size, start, set(covered)))
                result = search(frozenset(set(uncovered) - covered))
                if result is not None:
                    return result
                selected.pop()
                remaining[size] += 1
        failed.add(state)
        return None

    return search(frozenset(current - forced_covered))


def timetable_pattern_feasible(project: Project, groups: list[int]):
    return _complete_pattern_placement(project, groups, set()) is not None


def pattern_completion_plan(
    project: Project, assignment: Assignment, slots: list[int] | set[int]
):
    """Lập kế hoạch hoàn thành mẫu tiết từ phần lịch hiện có.

    Các tiết đã đặt có thể là một đoạn liền hoặc nhiều mảnh của cùng một cụm
    (ví dụ đã có tiết 1 và 3 của cụm 3 tiết). Hàm tìm cách bao phủ toàn bộ các
    tiết hiện có bằng những cụm hợp lệ, rồi trả về phần còn thiếu của mỗi cụm.
    """
    current = set(slots)
    maximum = project.days * project.sessions * project.periods_per_session
    if len(current) != len(list(slots)) or len(current) > assignment.periods_per_week:
        return None
    if any(slot < 0 or slot >= maximum for slot in current):
        return None
    if not assignment_requires_double(assignment):
        return [
            {
                "size": 1,
                "anchor_slots": tuple(),
                "candidate_starts": None,
            }
            for _ in range(assignment.periods_per_week - len(current))
        ]
    expected = assignment_groups(assignment)
    placements = _complete_pattern_placement(project, expected, current)
    if placements is None:
        return None
    ppd = project.sessions * project.periods_per_session
    plan = []
    for target_size, start, covered in placements:
        if not covered:
            plan.append(
                {
                    "size": target_size,
                    "anchor_slots": tuple(),
                    "candidate_starts": None,
                }
            )
            continue
        if len(covered) == target_size:
            continue
        alternative_starts = []
        for day in range(project.days):
            for session in range(project.sessions):
                base = day * ppd + session * project.periods_per_session
                for period in range(project.periods_per_session - target_size + 1):
                    candidate = base + period
                    candidate_slots = set(range(candidate, candidate + target_size))
                    if current.intersection(candidate_slots) != covered:
                        continue
                    # Chỉ ép candidate của chính cụm đang xét. Các cụm neo còn
                    # lại phải được phép tự chọn lại vị trí; nếu ghim chúng theo
                    # một nghiệm tạm thời, ta có thể loại nhầm một candidate mà
                    # thực tế thuộc một nghiệm hoàn chỉnh khác.
                    if (
                        _complete_pattern_placement(
                            project, expected, slots, [(target_size, candidate)]
                        )
                        is not None
                    ):
                        alternative_starts.append(candidate)
        plan.append(
            {
                "size": target_size,
                "anchor_slots": tuple(sorted(covered)),
                "candidate_starts": tuple(sorted(set(alternative_starts or [start]))),
            }
        )
    return plan


def remaining_pattern_groups(
    project: Project, assignment: Assignment, slots: list[int] | set[int]
):
    """Trả về kích thước đầy đủ của các cụm còn phải hoàn thành."""
    plan = pattern_completion_plan(project, assignment, slots)
    if plan is None:
        return None
    return [item["size"] for item in plan]


def assignment_pattern_matches(
    project: Project, assignment: Assignment, slots: list[int] | set[int]
):
    values = list(slots)
    if len(values) != len(set(values)) or len(values) != assignment.periods_per_week:
        return False
    if not assignment_requires_double(assignment):
        return True
    return pattern_slots_match(
        project,
        assignment_generated_pattern(assignment),
        assignment.periods_per_week,
        values,
    )


def assignment_completion_feasible(
    db: Session,
    project: Project,
    assignment: Assignment,
    proposed_slots: list[int] | set[int],
) -> bool:
    """Kiểm tra phần lịch thủ công có ít nhất một cách hoàn thành hợp lệ.

    Hàm này xét cả các ràng buộc thực tế: ô khóa, thời gian tránh,
    trùng lớp/giáo viên, số tiết tối đa
    trong ngày, giới hạn tiết liên tiếp và các cụm cố định.
    """
    values = list(proposed_slots)
    current = set(values)
    maximum = project.days * project.sessions * project.periods_per_session
    if len(values) != len(current) or len(current) > assignment.periods_per_week:
        return False
    if any(slot < 0 or slot >= maximum for slot in current):
        return False
    expected = assignment_groups(assignment)
    teacher = db.get(Teacher, assignment.teacher_id)
    school_class = db.get(SchoolClass, assignment.class_id)
    subject = db.get(Subject, assignment.subject_id)
    if not teacher or not school_class or not subject:
        return False

    ppd = project.sessions * project.periods_per_session
    global_blocked = parse_slots(project.blocked_slots_json)
    teacher_unavailable = parse_slots(teacher.unavailable_json)
    class_unavailable = parse_slots(school_class.unavailable_json)

    other_lessons = []
    for lesson in db.scalars(
        select(Lesson).where(Lesson.project_id == project.id)
    ).all():
        if lesson.assignment_id != assignment.id:
            other_lessons.append(lesson)

    teacher_busy = set()
    class_busy = set()
    teacher_day = Counter()
    base_subject_periods = defaultdict(set)
    for lesson in other_lessons:
        other = db.get(Assignment, lesson.assignment_id)
        if not other:
            continue
        day = lesson.slot // ppd
        if other.teacher_id == assignment.teacher_id:
            teacher_busy.add(lesson.slot)
            teacher_day[day] += 1
        if other.class_id == assignment.class_id:
            class_busy.add(lesson.slot)
            if other.subject_id == assignment.subject_id:
                inside = lesson.slot % ppd
                session = inside // project.periods_per_session
                period = inside % project.periods_per_session
                base_subject_periods[(day, session)].add(period)

    forbidden = (
        global_blocked
        | teacher_unavailable
        | class_unavailable
        | teacher_busy
        | class_busy
    )
    if current.intersection(forbidden):
        return False

    starts_by_size = {}
    for size in set(expected):
        candidates = []
        for day in range(project.days):
            for session in range(project.sessions):
                base = day * ppd + session * project.periods_per_session
                for period in range(project.periods_per_session - size + 1):
                    start = base + period
                    group = tuple(range(start, start + size))
                    if not set(group).intersection(forbidden):
                        candidates.append((start, group))
        starts_by_size[size] = candidates

    def compatible(left_start: int, left_size: int, right_start: int, right_size: int):
        left_end = left_start + left_size
        right_end = right_start + right_size
        if left_start < right_end and right_start < left_end:
            return False
        return True

    remaining = Counter(expected)
    selected = []
    selected_slots = set()
    added_teacher_day = Counter()
    added_subject_periods = defaultdict(set)

    def subject_limit_ok(group: tuple[int, ...]):
        touched = set()
        for slot in group:
            day = slot // ppd
            inside = slot % ppd
            session = inside // project.periods_per_session
            period = inside % project.periods_per_session
            touched.add((day, session))
            added_subject_periods[(day, session)].add(period)
        valid = True
        for key in touched:
            periods = sorted(base_subject_periods[key] | added_subject_periods[key])
            longest = run = 0
            previous = None
            for period in periods:
                run = run + 1 if previous is not None and period == previous + 1 else 1
                longest = max(longest, run)
                previous = period
            if longest > subject.max_consecutive:
                valid = False
                break
        for slot in group:
            day = slot // ppd
            inside = slot % ppd
            session = inside // project.periods_per_session
            period = inside % project.periods_per_session
            added_subject_periods[(day, session)].discard(period)
        return valid

    same_assignment_lessons = db.scalars(
        select(Lesson).where(
            Lesson.project_id == project.id,
            Lesson.assignment_id == assignment.id,
        )
    ).all()
    fixed_rows = db.scalars(
        select(FixedLesson).where(
            FixedLesson.project_id == project.id,
            FixedLesson.assignment_id == assignment.id,
        )
    ).all()

    fixed_placements = []
    for row in fixed_rows:
        size = fixed_row_size(project, assignment, row, same_assignment_lessons)
        if size < 1:
            return False
        if remaining[size] <= 0:
            return False
        group = tuple(range(row.slot, row.slot + size))
        if (row.slot, group) not in starts_by_size.get(size, []):
            return False
        if any(
            not compatible(row.slot, size, start, other_size)
            for other_size, start, _group in fixed_placements
        ):
            return False
        fixed_placements.append((size, row.slot, group))
        remaining[size] -= 1

    def add_group(size: int, start: int, group: tuple[int, ...]):
        day_counts = Counter(slot // ppd for slot in group)
        for day, count in day_counts.items():
            if (
                teacher_day[day] + added_teacher_day[day] + count
                > teacher.max_periods_day
            ):
                return False
        if not subject_limit_ok(group):
            return False
        for day, count in day_counts.items():
            added_teacher_day[day] += count
        for slot in group:
            day = slot // ppd
            inside = slot % ppd
            session = inside // project.periods_per_session
            period = inside % project.periods_per_session
            added_subject_periods[(day, session)].add(period)
        selected.append((size, start, group))
        selected_slots.update(group)
        return True

    def remove_group(size: int, start: int, group: tuple[int, ...]):
        selected.pop()
        for slot in group:
            selected_slots.remove(slot)
            day = slot // ppd
            added_teacher_day[day] -= 1
            inside = slot % ppd
            session = inside // project.periods_per_session
            period = inside % project.periods_per_session
            added_subject_periods[(day, session)].discard(period)

    for size, start, group in fixed_placements:
        if set(group).intersection(selected_slots) or not add_group(size, start, group):
            return False

    failed = set()

    def search():
        uncovered = current - selected_slots
        if sum(remaining.values()) == 0:
            return not uncovered and len(selected_slots) == assignment.periods_per_week
        state = (
            tuple(sorted(remaining.items())),
            tuple(sorted(uncovered)),
            tuple(sorted(selected_slots)),
        )
        if state in failed:
            return False

        candidate_sets = []
        if uncovered:
            target = min(uncovered)
            for size, count in remaining.items():
                if count <= 0:
                    continue
                options = [item for item in starts_by_size[size] if target in item[1]]
                if options:
                    candidate_sets.append((len(options), -size, size, options))
        else:
            for size, count in remaining.items():
                if count <= 0:
                    continue
                options = starts_by_size[size]
                candidate_sets.append((len(options), -size, size, options))
        if not candidate_sets:
            failed.add(state)
            return False

        for _count, _neg, size, raw_options in sorted(candidate_sets):
            options = sorted(raw_options, key=lambda item: item[0])
            for start, group in options:
                group_set = set(group)
                if group_set.intersection(selected_slots):
                    continue
                if any(
                    not compatible(start, size, other_start, other_size)
                    for other_size, other_start, _other_group in selected
                ):
                    continue
                if uncovered and not group_set.intersection(uncovered):
                    continue
                if not add_group(size, start, group):
                    continue
                remaining[size] -= 1
                if search():
                    return True
                remaining[size] += 1
                remove_group(size, start, group)
        failed.add(state)
        return False

    return search()


def assignment_pattern_label(assignment: Assignment):
    if assignment_requires_double(assignment):
        return (
            "bắt buộc tiết đôi ("
            + " + ".join(str(value) for value in assignment_groups(assignment))
            + ")"
        )
    if assignment_prefers_double(assignment):
        return "ưu tiên tiết đôi"
    return "xếp tiết tự do"


def bounded_text(value, label: str, max_length: int, *, required: bool = True) -> str:
    cleaned = str(value or "").strip()
    if required and not cleaned:
        raise HTTPException(400, f"{label} không được để trống")
    if len(cleaned) > max_length:
        raise HTTPException(400, f"{label} không được vượt quá {max_length} ký tự")
    return cleaned


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 401:
        if request.url.path.startswith("/api/"):
            return JSONResponse(
                {
                    "ok": False,
                    "message": "Phiên đăng nhập đã hết hạn.",
                    "detail": "Phiên đăng nhập đã hết hạn.",
                },
                status_code=401,
            )
        return RedirectResponse("/login", 303)
    if request.url.path.startswith("/api/"):
        detail = (
            exc.detail
            if exc.detail
            else (
                "Không tìm thấy tài nguyên yêu cầu."
                if exc.status_code == 404
                else "Yêu cầu không hợp lệ."
            )
        )
        return JSONResponse(
            {"ok": False, "message": str(detail), "detail": str(detail)},
            status_code=exc.status_code,
        )
    if exc.status_code == 404:
        return HTMLResponse("<h1>404 - Không tìm thấy trang</h1>", status_code=404)
    return HTMLResponse(
        f"<h1>{exc.status_code} - Lỗi hệ thống</h1>", status_code=exc.status_code
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(db_session)):
    raw = request.cookies.get("session")
    if raw:
        try:
            data = signer.loads(raw, max_age=SESSION_TTL_SECONDS)
            user = db.get(User, int(data["uid"]))
            if user and int(data.get("sv", -1)) == user.session_version:
                destination = (
                    "/teacher"
                    if user.role == "teacher"
                    else ("/projects" if is_admin(user) else "/logout")
                )
                return RedirectResponse(destination, 303)
        except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
            pass
    return templates.TemplateResponse("landing.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        "auth.html", {"request": request, "mode": "login", "error": None}
    )


@app.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(db_session),
):
    normalized_email = email.lower().strip()
    ip_key = client_rate_limit_key(request)
    if rate_limit_blocked(
        "login_ip", ip_key, limit=20, window_seconds=10 * 60
    ) or rate_limit_blocked(
        "login_email", normalized_email, limit=8, window_seconds=10 * 60
    ):
        return templates.TemplateResponse(
            "auth.html",
            {
                "request": request,
                "mode": "login",
                "error": "Bạn đã thử đăng nhập sai quá nhiều lần. Vui lòng đợi vài phút rồi thử lại.",
            },
            status_code=429,
        )
    user = db.scalar(select(User).where(User.email == normalized_email))
    if not user or not pwd.verify(password, user.password_hash):
        ip_limited = rate_limit_exceeded(
            "login_ip", ip_key, limit=20, window_seconds=10 * 60
        )
        email_limited = rate_limit_exceeded(
            "login_email", normalized_email, limit=8, window_seconds=10 * 60
        )
        if ip_limited or email_limited:
            return templates.TemplateResponse(
                "auth.html",
                {
                    "request": request,
                    "mode": "login",
                    "error": "Bạn đã thử đăng nhập sai quá nhiều lần. Vui lòng đợi vài phút rồi thử lại.",
                },
                status_code=429,
            )
        return templates.TemplateResponse(
            "auth.html",
            {
                "request": request,
                "mode": "login",
                "error": "Email hoặc mật khẩu không đúng",
            },
            status_code=400,
        )
    # Chỉ lỗi đăng nhập mới được tính vào rate-limit. Đăng nhập đúng xóa bucket
    # theo email để các lần đăng nhập hợp lệ không tự khóa tài khoản.
    clear_rate_limit_bucket("login_email", normalized_email)
    destination = (
        "/teacher"
        if user.role == "teacher"
        else ("/projects" if is_admin(user) else "/logout")
    )
    user.last_seen = _utc_now_iso()
    db.commit()
    res = RedirectResponse(destination, 303)
    set_session_cookie(res, user)
    return res


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    captcha_challenge, captcha_token = new_captcha("registration")
    return templates.TemplateResponse(
        "auth.html",
        {
            "request": request,
            "mode": "register",
            "error": None,
            "captcha_challenge": captcha_challenge,
            "captcha_token": captcha_token,
            "form_values": {},
        },
    )


def mask_email(email: str) -> str:
    local, separator, domain = email.partition("@")
    if not separator:
        return "***"
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'*' * max(2, len(local) - len(visible))}@{domain}"


def registration_verification_for_token(
    token: str,
    db: Session,
    *,
    lock: bool = False,
) -> RegistrationVerification | None:
    try:
        data = registration_signer.loads(token, max_age=REGISTRATION_OTP_TTL_SECONDS)
        query = select(RegistrationVerification).where(
            RegistrationVerification.id == int(data["id"])
        )
        if lock:
            query = query.with_for_update()
        verification = db.scalar(query)
        nonce_hash = hashlib.sha256(str(data["nonce"]).encode()).hexdigest()
        if not verification or not hmac.compare_digest(
            verification.token_hash, nonce_hash
        ):
            return None
        return verification
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None


def registration_otp_context(
    request: Request,
    verification: RegistrationVerification | None,
    verification_token: str,
    error: str | None = None,
):
    captcha_challenge, captcha_token = new_captcha("registration_resend")
    return {
        "request": request,
        "mode": "register_otp",
        "error": error,
        "verification_token": verification_token,
        "masked_email": mask_email(verification.email)
        if verification
        else "email của bạn",
        "target_teacher_name": verification.name if verification else None,
        "captcha_challenge": captcha_challenge,
        "captcha_token": captcha_token,
    }


@app.post("/register")
def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    captcha_answer: str = Form(...),
    captcha_token: str = Form(...),
    human_confirm: Optional[str] = Form(None),
    website: str = Form(""),
    db: Session = Depends(db_session),
):
    name = name.strip()
    email = email.lower().strip()
    fresh_challenge, fresh_captcha_token = new_captcha("registration")
    context = {
        "request": request,
        "mode": "register",
        "error": None,
        "captcha_challenge": fresh_challenge,
        "captcha_token": fresh_captcha_token,
        "form_values": {"name": name, "email": email},
    }
    if rate_limit_exceeded(
        "register_ip", client_rate_limit_key(request), limit=12, window_seconds=15 * 60
    ) or rate_limit_exceeded("register_email", email, limit=5, window_seconds=15 * 60):
        context["error"] = (
            "Có quá nhiều yêu cầu đăng ký. Vui lòng đợi vài phút rồi thử lại."
        )
        return templates.TemplateResponse("auth.html", context, status_code=429)
    if (
        website.strip()
        or human_confirm != "yes"
        or not captcha_is_valid(captcha_token, captcha_answer, "registration")
    ):
        context["error"] = (
            "Xác minh bảo mật không hợp lệ hoặc thao tác quá nhanh. Hãy hoàn thành thử thách mới."
        )
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if not name:
        context["error"] = "Tên giáo viên không được để trống"
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if len(name) > 120:
        context["error"] = "Tên giáo viên không được vượt quá 120 ký tự"
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if len(email) > 255:
        context["error"] = "Email không được vượt quá 255 ký tự"
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if len(password) < MIN_PASSWORD_LENGTH:
        context["error"] = f"Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự"
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if password != password_confirm:
        context["error"] = "Hai lần nhập mật khẩu không khớp"
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if not email or "@" not in email:
        context["error"] = "Email không hợp lệ"
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if db.scalar(select(User).where(User.email == email)):
        context["error"] = "Email đã tồn tại"
        return templates.TemplateResponse("auth.html", context, status_code=400)

    now = datetime.now(timezone.utc)
    for expired in db.scalars(
        select(RegistrationVerification).where(
            RegistrationVerification.expires_at <= now.isoformat()
        )
    ).all():
        db.delete(expired)
    db.flush()

    email_verification = db.scalar(
        select(RegistrationVerification)
        .where(RegistrationVerification.email == email)
        .with_for_update()
    )
    if (
        email_verification
        and datetime.fromisoformat(email_verification.resend_available_at) > now
    ):
        context["error"] = (
            "Mã OTP vừa được gửi tới email này. Vui lòng chờ 60 giây trước khi gửi lại."
        )
        return templates.TemplateResponse("auth.html", context, status_code=429)

    otp = f"{secrets.randbelow(1_000_000):06d}"
    nonce = secrets.token_urlsafe(32)
    try:
        if not send_registration_otp_email(email, otp, name):
            raise RuntimeError("SMTP chưa được cấu hình")
    except (OSError, smtplib.SMTPException, RuntimeError, ValueError) as exc:
        logger.exception("Could not send registration OTP to %s: %s", email, exc)
        context["error"] = (
            "Chưa thể gửi mã OTP. Vui lòng kiểm tra email hoặc thử lại sau."
        )
        return templates.TemplateResponse("auth.html", context, status_code=503)

    if email_verification is not None:
        db.delete(email_verification)
        db.flush()
    verification = RegistrationVerification(
        email=email,
        name=name,
        password_hash=pwd.hash(password),
        otp_hash=registration_otp_hash(email, otp),
        token_hash=hashlib.sha256(nonce.encode()).hexdigest(),
        expires_at=(now + timedelta(seconds=REGISTRATION_OTP_TTL_SECONDS)).isoformat(),
        resend_available_at=(
            now + timedelta(seconds=REGISTRATION_OTP_RESEND_SECONDS)
        ).isoformat(),
        attempt_count=0,
    )
    db.add(verification)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        context["error"] = (
            "Email này đang được xác minh ở một phiên khác. Hãy thử lại sau."
        )
        return templates.TemplateResponse("auth.html", context, status_code=409)
    verification_token = registration_signer.dumps(
        {"id": verification.id, "nonce": nonce}
    )
    resend_challenge, resend_captcha = new_captcha("registration_resend")
    return templates.TemplateResponse(
        "auth.html",
        {
            "request": request,
            "mode": "register_otp",
            "error": None,
            "verification_token": verification_token,
            "masked_email": mask_email(email),
            "target_teacher_name": name,
            "captcha_challenge": resend_challenge,
            "captcha_token": resend_captcha,
        },
    )


@app.post("/register/verify", response_class=HTMLResponse)
def verify_registration_otp(
    request: Request,
    verification_token: str = Form(...),
    otp: str = Form(...),
    db: Session = Depends(db_session),
):
    verification = registration_verification_for_token(
        verification_token, db, lock=True
    )
    now = datetime.now(timezone.utc)
    if not verification or datetime.fromisoformat(verification.expires_at) <= now:
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                verification,
                verification_token,
                "Mã OTP không hợp lệ hoặc đã hết hạn. Hãy đăng ký lại.",
            ),
            status_code=400,
        )
    if verification.attempt_count >= REGISTRATION_OTP_MAX_ATTEMPTS:
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                verification,
                verification_token,
                "Bạn đã nhập sai quá số lần cho phép. Hãy gửi lại mã OTP mới.",
            ),
            status_code=429,
        )
    normalized_otp = otp.strip()
    if (
        not normalized_otp.isdigit()
        or len(normalized_otp) != 6
        or not hmac.compare_digest(
            verification.otp_hash,
            registration_otp_hash(verification.email, normalized_otp),
        )
    ):
        verification.attempt_count += 1
        remaining = max(0, REGISTRATION_OTP_MAX_ATTEMPTS - verification.attempt_count)
        db.commit()
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                verification,
                verification_token,
                f"Mã OTP không đúng. Bạn còn {remaining} lần thử.",
            ),
            status_code=400,
        )

    if db.scalar(select(User.id).where(User.email == verification.email)) is not None:
        db.delete(verification)
        db.commit()
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                None,
                verification_token,
                "Email này đã được đăng ký. Hãy chuyển sang trang đăng nhập.",
            ),
            status_code=409,
        )

    teacher_name = verification.name.strip()
    # Đăng ký chỉ tạo tài khoản đăng nhập. Không tạo Teacher trong bất kỳ
    # project nào; hồ sơ giáo viên phục vụ xếp lịch chỉ do quản trị viên tạo/cấu hình.
    user = User(
        name=teacher_name,
        email=verification.email,
        password_hash=verification.password_hash,
        role="teacher",
    )
    db.add(user)
    try:
        db.flush()
        db.delete(verification)
        db.commit()
    except IntegrityError:
        db.rollback()
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                None,
                verification_token,
                "Email này vừa được tài khoản khác sử dụng. Hãy đăng nhập hoặc đăng ký lại.",
            ),
            status_code=409,
        )
    response = RedirectResponse("/teacher", 303)
    set_session_cookie(response, user)
    return response


@app.post("/register/resend", response_class=HTMLResponse)
def resend_registration_otp(
    request: Request,
    verification_token: str = Form(...),
    captcha_answer: str = Form(...),
    captcha_token: str = Form(...),
    human_confirm: Optional[str] = Form(None),
    website: str = Form(""),
    db: Session = Depends(db_session),
):
    verification = registration_verification_for_token(
        verification_token, db, lock=True
    )
    if not verification:
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                None,
                verification_token,
                "Phiên xác minh không còn hợp lệ. Hãy đăng ký lại.",
            ),
            status_code=400,
        )
    if rate_limit_exceeded(
        "register_resend_ip",
        client_rate_limit_key(request),
        limit=10,
        window_seconds=15 * 60,
    ) or rate_limit_exceeded(
        "register_resend_email", verification.email, limit=5, window_seconds=15 * 60
    ):
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                verification,
                verification_token,
                "Bạn đã yêu cầu gửi lại mã quá nhiều lần. Vui lòng đợi rồi thử lại.",
            ),
            status_code=429,
        )
    if (
        website.strip()
        or human_confirm != "yes"
        or not captcha_is_valid(captcha_token, captcha_answer, "registration_resend")
    ):
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                verification,
                verification_token,
                "Xác minh bảo mật không đúng hoặc thao tác quá nhanh.",
            ),
            status_code=400,
        )
    now = datetime.now(timezone.utc)
    if datetime.fromisoformat(verification.resend_available_at) > now:
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                verification,
                verification_token,
                "Vui lòng chờ đủ 60 giây trước khi yêu cầu mã mới.",
            ),
            status_code=429,
        )
    otp = f"{secrets.randbelow(1_000_000):06d}"
    try:
        if not send_registration_otp_email(
            verification.email,
            otp,
            verification.name,
        ):
            raise RuntimeError("SMTP chưa được cấu hình")
    except (OSError, smtplib.SMTPException, RuntimeError, ValueError) as exc:
        logger.exception(
            "Could not resend registration OTP to %s: %s", verification.email, exc
        )
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                verification,
                verification_token,
                "Chưa thể gửi lại mã OTP. Vui lòng thử lại sau.",
            ),
            status_code=503,
        )
    verification.otp_hash = registration_otp_hash(verification.email, otp)
    nonce = secrets.token_urlsafe(32)
    verification.token_hash = hashlib.sha256(nonce.encode()).hexdigest()
    verification.expires_at = (
        now + timedelta(seconds=REGISTRATION_OTP_TTL_SECONDS)
    ).isoformat()
    verification.resend_available_at = (
        now + timedelta(seconds=REGISTRATION_OTP_RESEND_SECONDS)
    ).isoformat()
    verification.attempt_count = 0
    db.commit()
    refreshed_token = registration_signer.dumps({"id": verification.id, "nonce": nonce})
    return templates.TemplateResponse(
        "auth.html",
        registration_otp_context(
            request,
            verification,
            refreshed_token,
        ),
    )


@app.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request):
    captcha_challenge, captcha_token = new_captcha()
    return templates.TemplateResponse(
        "forgot_password.html",
        {
            "request": request,
            "captcha_challenge": captcha_challenge,
            "captcha_token": captcha_token,
            "error": None,
            "submitted": False,
            "dev_reset_link": None,
        },
    )


@app.post("/forgot-password", response_class=HTMLResponse)
def forgot_password(
    request: Request,
    email: str = Form(...),
    not_robot: Optional[str] = Form(None),
    captcha_answer: str = Form(...),
    captcha_token: str = Form(...),
    db: Session = Depends(db_session),
):
    normalized_email = email.lower().strip()
    if rate_limit_exceeded(
        "forgot_ip", client_rate_limit_key(request), limit=8, window_seconds=15 * 60
    ) or rate_limit_exceeded(
        "forgot_email", normalized_email, limit=4, window_seconds=30 * 60
    ):
        fresh_challenge, fresh_token = new_captcha()
        return templates.TemplateResponse(
            "forgot_password.html",
            {
                "request": request,
                "captcha_challenge": fresh_challenge,
                "captcha_token": fresh_token,
                "error": "Bạn đã gửi quá nhiều yêu cầu. Vui lòng đợi một lúc rồi thử lại.",
                "submitted": False,
                "dev_reset_link": None,
            },
            status_code=429,
        )
    if not_robot != "yes" or not captcha_is_valid(captcha_token, captcha_answer):
        fresh_challenge, fresh_token = new_captcha()
        return templates.TemplateResponse(
            "forgot_password.html",
            {
                "request": request,
                "captcha_challenge": fresh_challenge,
                "captcha_token": fresh_token,
                "error": "Xác minh trực quan chưa đúng. Vui lòng thử lại.",
                "submitted": False,
                "dev_reset_link": None,
            },
            status_code=400,
        )

    account = db.scalar(select(User).where(User.email == normalized_email))
    dev_reset_link = None
    allow_local_link = development_reset_links_enabled(request)
    smtp_configured = bool(os.getenv("SMTP_HOST"))
    base_url = public_base_url(request)
    if account and (smtp_configured or allow_local_link) and base_url:
        nonce = secrets.token_urlsafe(32)
        account.reset_token_hash = hashlib.sha256(nonce.encode()).hexdigest()
        account.reset_token_expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=RESET_TOKEN_TTL_SECONDS)
        ).isoformat()
        db.commit()
        token = reset_signer.dumps({"uid": account.id, "nonce": nonce})
        reset_url = f"{base_url}/reset-password/{token}"
        email_sent = False
        if smtp_configured:
            try:
                email_sent = send_password_reset_email(account.email, reset_url)
                if email_sent:
                    logger.info(
                        "Password-reset email accepted by SMTP for %s", account.email
                    )
            except (OSError, smtplib.SMTPException, ValueError) as exc:
                email_sent = False
                logger.exception(
                    "Could not send password-reset email to %s: %s", account.email, exc
                )
        if allow_local_link and not email_sent:
            dev_reset_link = reset_url
    elif account and smtp_configured and not base_url:
        logger.error(
            "Password reset skipped because no public server URL is configured"
        )

    fresh_challenge, fresh_token = new_captcha()
    return templates.TemplateResponse(
        "forgot_password.html",
        {
            "request": request,
            "captcha_challenge": fresh_challenge,
            "captcha_token": fresh_token,
            "error": None,
            "submitted": True,
            "dev_reset_link": dev_reset_link,
        },
    )


def reset_account_for_token(token: str, db: Session) -> Optional[User]:
    try:
        data = reset_signer.loads(token, max_age=RESET_TOKEN_TTL_SECONDS)
        account = db.get(User, int(data["uid"]))
        nonce_hash = hashlib.sha256(str(data["nonce"]).encode()).hexdigest()
        if not account or not account.reset_token_hash:
            return None
        if not hmac.compare_digest(account.reset_token_hash, nonce_hash):
            return None
        expires_at = datetime.fromisoformat(account.reset_token_expires_at or "")
        if expires_at < datetime.now(timezone.utc):
            return None
        return account
    except (BadSignature, SignatureExpired, KeyError, ValueError, TypeError):
        return None


@app.get("/reset-password/{token}", response_class=HTMLResponse)
def reset_password_page(
    token: str, request: Request, db: Session = Depends(db_session)
):
    account = reset_account_for_token(token, db)
    return templates.TemplateResponse(
        "reset_password.html",
        {
            "request": request,
            "token": token,
            "valid": account is not None,
            "error": None,
            "success": False,
        },
        status_code=200 if account else 400,
    )


@app.post("/reset-password/{token}", response_class=HTMLResponse)
def reset_password(
    token: str,
    request: Request,
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(db_session),
):
    account = reset_account_for_token(token, db)
    error = None
    if not account:
        error = (
            "Liên kết đặt lại mật khẩu không hợp lệ, đã hết hạn hoặc đã được sử dụng."
        )
    elif len(password) < MIN_PASSWORD_LENGTH:
        error = f"Mật khẩu mới phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự."
    elif password != password_confirm:
        error = "Hai lần nhập mật khẩu không khớp."
    if error:
        return templates.TemplateResponse(
            "reset_password.html",
            {
                "request": request,
                "token": token,
                "valid": account is not None,
                "error": error,
                "success": False,
            },
            status_code=400,
        )

    account.password_hash = pwd.hash(password)
    account.session_version += 1
    account.reset_token_hash = None
    account.reset_token_expires_at = None
    db.commit()
    return templates.TemplateResponse(
        "reset_password.html",
        {
            "request": request,
            "token": token,
            "valid": False,
            "error": None,
            "success": True,
        },
    )


@app.get("/logout")
def logout():
    res = RedirectResponse("/", 303)
    res.delete_cookie("session")
    return res


@app.get("/api/chat/schools")
def chat_schools(
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    schools = user_schools(user, db)
    return {
        "schools": [{"id": school.id, "name": school.name} for school in schools],
        "default_school_id": schools[0].id if schools else None,
    }


@app.get("/api/chat/general/messages")
def general_chat_messages(
    school_id: int,
    limit: int = 50,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    school = db.get(School, school_id)
    if not school or not user_can_access_school(user, school_id, db):
        raise HTTPException(403, "Bạn không có quyền truy cập chat của trường này")

    safe_limit = max(1, min(int(limit or 50), 100))
    rows = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.school_id == school_id)
        .order_by(ChatMessage.id.desc())
        .limit(safe_limit)
    ).all()
    ordered_rows = list(reversed(rows))
    reply_ids = {
        int(row.reply_to_id)
        for row in ordered_rows
        if row.reply_to_id is not None
    }
    reply_rows = {}
    if reply_ids:
        reply_rows = {
            row.id: row
            for row in db.scalars(
                select(ChatMessage).where(
                    ChatMessage.id.in_(reply_ids),
                    ChatMessage.school_id == school_id,
                )
            ).all()
        }

    def reply_preview(row: ChatMessage) -> dict | None:
        if row.reply_to_id is None:
            return None
        target = reply_rows.get(int(row.reply_to_id))
        if target is None:
            return {
                "id": int(row.reply_to_id),
                "user_name": "Tin nhắn không còn tồn tại",
                "content": "Tin nhắn không còn tồn tại",
                "deleted": True,
            }
        deleted = bool(target.deleted_at)
        return {
            "id": target.id,
            "user_name": target.user_name or "Tài khoản đã xóa",
            "content": "Tin nhắn đã bị xóa" if deleted else target.content,
            "deleted": deleted,
        }

    messages = [
        {
            "id": row.id,
            "school_id": row.school_id,
            "user_id": row.user_id,
            "user_name": row.user_name or "Tài khoản đã xóa",
            "content": "Tin nhắn đã bị xóa" if row.deleted_at else row.content,
            "created_at": row.created_at,
            "edited_at": row.edited_at,
            "deleted_at": row.deleted_at,
            "reply_to_id": row.reply_to_id,
            "reply": reply_preview(row),
        }
        for row in ordered_rows
    ]
    return {"school": {"id": school.id, "name": school.name}, "messages": messages}


async def _broadcast_delayed_offline(user_id: int, last_seen: str) -> None:
    # Avoid Online -> Offline -> Online flicker when the browser simply reloads.
    await asyncio.sleep(4)
    if realtime_manager.is_online(user_id):
        return
    db = SessionLocal()
    try:
        account = db.get(User, user_id)
        if not account:
            return
        recipients = presence_recipients_for_user(db, account)
        await realtime_manager.broadcast(
            {
                "type": "presence",
                "user_id": user_id,
                "online": False,
                "last_seen": last_seen,
                "online_count": realtime_manager.online_count_for(recipients),
            },
            only_user_ids=recipients,
        )
        await broadcast_school_presence(account, False, last_seen)
    finally:
        db.close()


def _payload_school_id(payload: dict) -> int | None:
    try:
        value = payload.get("school_id")
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


@app.websocket("/ws/realtime")
async def realtime_socket(websocket: WebSocket):
    account = await asyncio.to_thread(websocket_session_user, websocket)
    if account is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    connection_id = secrets.token_urlsafe(12)
    first_connection = realtime_manager.add(account.id, connection_id, websocket)
    last_seen = touch_user_last_seen(account.id)

    db = SessionLocal()
    try:
        visible_user_ids = presence_visible_user_ids(db, account)
        presence_recipients = presence_recipients_for_user(db, account)
    finally:
        db.close()

    await websocket.send_json(
        {
            "type": "ready",
            "user_id": account.id,
            "user_name": account.name,
            "online_user_ids": realtime_manager.online_user_ids_for(visible_user_ids),
            "online_count": realtime_manager.online_count_for(visible_user_ids),
        }
    )
    if first_connection:
        await realtime_manager.broadcast(
            {
                "type": "presence",
                "user_id": account.id,
                "online": True,
                "last_seen": last_seen,
                "online_count": realtime_manager.online_count_for(presence_recipients),
            },
            only_user_ids=presence_recipients,
        )
        await broadcast_school_presence(account, True, last_seen)

    try:
        while True:
            # Even an idle socket must expire. Revalidate before activity as
            # well as chat events; never allow heartbeat to bypass revocation.
            try:
                payload = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=realtime_manager.SESSION_CHECK_INTERVAL_SECONDS,
                )
            except asyncio.TimeoutError:
                payload = None
            refreshed = await asyncio.to_thread(websocket_session_user, websocket)
            if refreshed is None:
                await websocket.close(code=4401)
                break
            account = refreshed
            if not isinstance(payload, dict):
                continue
            event_type = str(payload.get("type") or "").strip()

            if event_type == "activity":
                touch_user_last_seen(account.id, min_interval_seconds=45)
                realtime_manager.touch(account.id, connection_id)
                presence_db = SessionLocal()
                try:
                    visible_user_ids = presence_visible_user_ids(presence_db, account)
                finally:
                    presence_db.close()
                await websocket.send_json(
                    {
                        "type": "presence_sync",
                        "online_user_ids": realtime_manager.online_user_ids_for(
                            visible_user_ids
                        ),
                        "online_count": realtime_manager.online_count_for(
                            visible_user_ids
                        ),
                    }
                )
                continue

            db = SessionLocal()
            try:
                current = db.get(User, account.id)
                if not current or current.session_version != account.session_version:
                    await websocket.close(code=4401)
                    break

                if event_type == "room_join":
                    school_id = _payload_school_id(payload)
                    school = db.get(School, school_id) if school_id is not None else None
                    if not school or not user_can_access_school(current, school_id, db):
                        await websocket.send_json(
                            {"type": "chat_error", "message": "Bạn không có quyền truy cập trường này."}
                        )
                        continue
                    recipients = school_chat_user_ids(db, school_id)
                    await websocket.send_json(
                        {
                            "type": "room_ready",
                            "school_id": school.id,
                            "school_name": school.name,
                            "online_user_ids": realtime_manager.online_user_ids_for(recipients),
                            "online_count": realtime_manager.online_count_for(recipients),
                        }
                    )
                    continue

                if event_type == "typing":
                    school_id = _payload_school_id(payload)
                    if school_id is None or not user_can_access_school(current, school_id, db):
                        continue
                    recipients = school_chat_user_ids(db, school_id)
                    await realtime_manager.broadcast(
                        {
                            "type": "typing",
                            "school_id": school_id,
                            "user_id": current.id,
                            "user_name": current.name,
                            "typing": bool(payload.get("typing")),
                        },
                        exclude_user_id=current.id,
                        only_user_ids=recipients,
                    )
                    continue

                if event_type not in {"chat_send", "chat_edit", "chat_delete"}:
                    continue

                if event_type == "chat_send":
                    school_id = _payload_school_id(payload)
                    school = db.get(School, school_id) if school_id is not None else None
                    if not school or not user_can_access_school(current, school_id, db):
                        await websocket.send_json(
                            {"type": "chat_error", "message": "Bạn không có quyền gửi tin nhắn vào trường này."}
                        )
                        continue
                    content = str(payload.get("content") or "").strip()
                    if not content:
                        continue
                    if len(content) > 2000:
                        await websocket.send_json(
                            {"type": "chat_error", "message": "Tin nhắn tối đa 2000 ký tự."}
                        )
                        continue

                    reply_to_id = payload.get("reply_to_id")
                    try:
                        reply_to_id = int(reply_to_id) if reply_to_id is not None else None
                    except (TypeError, ValueError):
                        reply_to_id = None
                    reply_target = None
                    if reply_to_id is not None:
                        reply_target = db.get(ChatMessage, reply_to_id)
                        if reply_target is None or reply_target.school_id != school_id:
                            await websocket.send_json(
                                {"type": "chat_error", "message": "Tin nhắn được trả lời không còn tồn tại trong trường này."}
                            )
                            continue

                    created_at = _utc_now_iso()
                    row = ChatMessage(
                        school_id=school_id,
                        user_id=current.id,
                        user_name=current.name,
                        user_email=current.email,
                        content=content,
                        reply_to_id=reply_to_id,
                        created_at=created_at,
                    )
                    current.last_seen = created_at
                    db.add(row)
                    db.commit()
                    db.refresh(row)
                    reply_payload = None
                    if reply_target is not None:
                        reply_deleted = bool(reply_target.deleted_at)
                        reply_payload = {
                            "id": reply_target.id,
                            "user_name": reply_target.user_name or "Tài khoản đã xóa",
                            "content": "Tin nhắn đã bị xóa" if reply_deleted else reply_target.content,
                            "deleted": reply_deleted,
                        }
                    recipients = school_chat_user_ids(db, school_id)
                    await realtime_manager.broadcast(
                        {
                            "type": "chat_message",
                            "school_id": school_id,
                            "message": {
                                "id": row.id,
                                "school_id": school_id,
                                "user_id": current.id,
                                "user_name": current.name,
                                "content": row.content,
                                "created_at": row.created_at,
                                "edited_at": row.edited_at,
                                "deleted_at": row.deleted_at,
                                "reply_to_id": row.reply_to_id,
                                "reply": reply_payload,
                            },
                        },
                        only_user_ids=recipients,
                    )
                    continue

                message_id = payload.get("message_id")
                try:
                    message_id = int(message_id)
                except (TypeError, ValueError):
                    await websocket.send_json(
                        {"type": "chat_error", "message": "Tin nhắn không hợp lệ."}
                    )
                    continue

                row = db.get(ChatMessage, message_id)
                if row is None or row.school_id is None:
                    await websocket.send_json(
                        {"type": "chat_error", "message": "Tin nhắn không còn tồn tại."}
                    )
                    continue
                if not user_can_access_school(current, row.school_id, db):
                    await websocket.send_json(
                        {"type": "chat_error", "message": "Bạn không có quyền thao tác tin nhắn này."}
                    )
                    continue

                recipients = school_chat_user_ids(db, row.school_id)
                if event_type == "chat_edit":
                    if row.deleted_at:
                        await websocket.send_json(
                            {"type": "chat_error", "message": "Tin nhắn đã bị xóa."}
                        )
                        continue
                    if row.user_id != current.id:
                        await websocket.send_json(
                            {"type": "chat_error", "message": "Bạn chỉ có thể sửa tin nhắn của mình."}
                        )
                        continue
                    content = str(payload.get("content") or "").strip()
                    if not content:
                        await websocket.send_json(
                            {"type": "chat_error", "message": "Tin nhắn không được để trống."}
                        )
                        continue
                    if len(content) > 2000:
                        await websocket.send_json(
                            {"type": "chat_error", "message": "Tin nhắn tối đa 2000 ký tự."}
                        )
                        continue
                    edited_at = _utc_now_iso()
                    row.content = content
                    row.edited_at = edited_at
                    current.last_seen = edited_at
                    db.commit()
                    await realtime_manager.broadcast(
                        {
                            "type": "chat_message_updated",
                            "school_id": row.school_id,
                            "message": {
                                "id": row.id,
                                "content": row.content,
                                "edited_at": row.edited_at,
                            },
                        },
                        only_user_ids=recipients,
                    )
                    continue

                can_delete = row.user_id == current.id or current.role == "super_admin"
                if not can_delete:
                    await websocket.send_json(
                        {"type": "chat_error", "message": "Bạn không có quyền xóa tin nhắn này."}
                    )
                    continue
                if row.deleted_at:
                    continue
                deleted_at = _utc_now_iso()
                row.content = ""
                row.deleted_at = deleted_at
                current.last_seen = deleted_at
                db.commit()
                await realtime_manager.broadcast(
                    {
                        "type": "chat_message_deleted",
                        "school_id": row.school_id,
                        "message_id": row.id,
                        "deleted_at": row.deleted_at,
                    },
                    only_user_ids=recipients,
                )
            finally:
                db.close()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Realtime WebSocket error for user_id=%s", account.id)
    finally:
        # Remove this socket before broadcasting cleanup events, so a revoked
        # connection is not selected again while its close handler is running.
        became_offline = realtime_manager.remove(account.id, connection_id)
        # Clear typing state in every school the account can access.
        db = SessionLocal()
        try:
            for school_id in user_school_ids(account, db):
                recipients = school_chat_user_ids(db, school_id)
                await realtime_manager.broadcast(
                    {
                        "type": "typing",
                        "school_id": school_id,
                        "user_id": account.id,
                        "user_name": account.name,
                        "typing": False,
                    },
                    exclude_user_id=account.id,
                    only_user_ids=recipients,
                )
        finally:
            db.close()
        if became_offline:
            last_seen = touch_user_last_seen(account.id)
            asyncio.create_task(_broadcast_delayed_offline(account.id, last_seen))


@app.get("/api/mobile/config")
def mobile_config():
    # Legacy endpoint kept for backward compatibility. The V1 APK discovers the backend
    # through Firebase Hosting config.json and does not depend on this endpoint.
    return JSONResponse(
        {"apk_base_url": APP_BASE_URL},
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_admin(user):
        raise HTTPException(403, "Chỉ quản trị viên được quản lý tài khoản")
    projects_query = select(Project)
    if not is_super_admin(user):
        school_ids = user_school_ids(user, db)
        if school_ids:
            projects_query = projects_query.where(Project.school_id.in_(school_ids))
        else:
            projects_query = projects_query.where(Project.id == -1)
    projects = db.scalars(projects_query.order_by(Project.id.asc())).all()
    all_schools = db.scalars(select(School).order_by(School.name.asc())).all()
    assignable_school_ids = (
        {school.id for school in all_schools}
        if is_super_admin(user)
        else user_school_ids(user, db)
    )
    school_assignments = defaultdict(set)
    for link in db.scalars(select(UserSchool)).all():
        school_assignments[link.user_id].add(link.school_id)
    school_name_by_id = {school.id: school.name for school in all_schools}
    school_names_by_account = {
        account_id: [
            school_name_by_id[school_id]
            for school_id in sorted(school_ids)
            if school_id in school_name_by_id
        ]
        for account_id, school_ids in school_assignments.items()
    }
    all_users = db.scalars(select(User).order_by(User.id.asc())).all()
    users = [
        account for account in all_users if admin_can_manage_account(user, account, db)
    ]
    managed_account_ids = {
        account.id
        for account in users
        if account.role == "teacher" and admin_can_manage_account(user, account, db)
    }
    chatbot_error_logs = []
    chatbot_error_log_count = 0
    if is_super_admin(user):
        chatbot_error_log_count = db.scalar(select(func.count(ChatbotErrorLog.id))) or 0
        chatbot_error_logs = db.scalars(
            select(ChatbotErrorLog).order_by(ChatbotErrorLog.id.desc()).limit(100)
        ).all()
    return templates.TemplateResponse(
        "users.html",
        {
            "request": request,
            "user": user,
            "greeting_name": user_greeting_name(user),
            "users": users,
            "managed_account_ids": managed_account_ids,
            "schools": all_schools,
            "assignable_school_ids": assignable_school_ids,
            "school_assignments": school_assignments,
            "school_names_by_account": school_names_by_account,
            "chatbot_error_logs": chatbot_error_logs,
            "chatbot_error_log_count": chatbot_error_log_count,
            "online_user_ids": realtime_manager.online_user_ids_for({account.id for account in users}),
            **chatbot_ui_context(projects[-1] if projects else None),
        },
    )


@app.post("/admin/schools/create")
def create_school_from_account_management(
    name: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_super_admin(user):
        raise HTTPException(403, "Chỉ super admin được tạo trường")
    clean_name = bounded_text(name, "Tên trường", 200)
    existing = db.scalar(select(School).where(func.lower(School.name) == clean_name.lower()))
    if existing:
        return RedirectResponse("/admin/users", 303)
    db.add(School(name=clean_name))
    db.commit()
    return RedirectResponse("/admin/users", 303)


@app.post("/admin/schools/{school_id}/rename")
def rename_school_from_account_management(
    school_id: int,
    name: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_super_admin(user):
        raise HTTPException(403, "Chỉ super admin được sửa tên trường")

    school = db.get(School, school_id)
    if not school:
        raise HTTPException(404, "Không tìm thấy trường")

    try:
        clean_name = bounded_text(name, "Tên trường", 200)
    except HTTPException as exc:
        return redirect_with_notice("/admin/users", str(exc.detail))

    duplicate = db.scalar(
        select(School).where(
            School.id != school.id,
            func.lower(School.name) == clean_name.lower(),
        )
    )
    if duplicate:
        return redirect_with_notice("/admin/users", "Tên trường này đã tồn tại")

    if school.name != clean_name:
        school.name = clean_name
        # Project vẫn lưu school_name để hiển thị/xuất Excel, vì vậy cần đồng bộ
        # theo school_id mỗi khi đổi tên trường.
        projects = db.scalars(
            select(Project).where(Project.school_id == school.id)
        ).all()
        for project in projects:
            project.school_name = clean_name
        db.commit()

    return RedirectResponse("/admin/users", 303)


@app.post("/admin/users/{account_id}/schools")
def update_account_schools(
    account_id: int,
    school_ids: list[int] = Form(default=[]),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_admin(user):
        raise HTTPException(403, "Chỉ quản trị viên được quản lý tài khoản")
    account = db.get(User, account_id)
    if not account:
        raise HTTPException(404, "Không tìm thấy tài khoản")

    if is_super_admin(user):
        if account.role not in {"admin", "teacher"}:
            raise HTTPException(403, "Super admin chỉ gán trường cho quản trị viên và giáo viên")
        allowed_ids = set(db.scalars(select(School.id)).all())
    else:
        if account.role != "teacher":
            raise HTTPException(403, "Quản trị viên chỉ được gán trường cho giáo viên")
        if not admin_can_manage_account(user, account, db):
            raise HTTPException(403, "Giáo viên nằm ngoài phạm vi trường bạn quản lý")
        allowed_ids = user_school_ids(user, db)
        if not allowed_ids:
            raise HTTPException(403, "Tài khoản quản trị viên chưa được gán trường")

    requested_ids = {int(value) for value in school_ids}
    if not requested_ids.issubset(allowed_ids):
        raise HTTPException(403, "Có trường nằm ngoài phạm vi quản lý")

    existing = set(
        db.scalars(
            select(UserSchool.school_id).where(UserSchool.user_id == account.id)
        ).all()
    )
    if is_super_admin(user):
        desired = requested_ids
    else:
        # Admin thường chỉ thay đổi các trường thuộc phạm vi của mình, không được
        # vô tình xóa liên kết của giáo viên với trường do admin khác quản lý.
        desired = (existing - allowed_ids) | requested_ids

    to_remove = existing - desired
    if to_remove:
        db.execute(
            delete(UserSchool).where(
                UserSchool.user_id == account.id,
                UserSchool.school_id.in_(to_remove),
            )
        )
    for school_id in sorted(desired - existing):
        db.add(
            UserSchool(
                user_id=account.id,
                school_id=school_id,
                assigned_by_user_id=user.id,
            )
        )
    db.commit()
    return RedirectResponse("/admin/users", 303)


@app.post("/admin/chatbot-logs/clear")
def clear_chatbot_error_logs(
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_super_admin(user):
        raise HTTPException(403, "Chỉ super admin được xóa log chatbot")
    db.execute(delete(ChatbotErrorLog))
    db.commit()
    return RedirectResponse("/admin/users#chatbot-logs", 303)


@app.post("/admin/users/{account_id}/update")
def update_account(
    account_id: int,
    name: str = Form(""),
    password: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_admin(user):
        raise HTTPException(403, "Chỉ quản trị viên được quản lý tài khoản")
    account = db.get(User, account_id)
    if not account or not admin_can_manage_account(user, account, db):
        raise HTTPException(404, "Không tìm thấy tài khoản trong phạm vi quản lý")
    try:
        clean_name = bounded_text(name, "Họ tên", 120)
    except HTTPException as exc:
        return redirect_with_notice("/admin/users", str(exc.detail))

    password_changed = bool(password.strip())
    clean_password = password.strip()
    if password_changed and len(clean_password) < MIN_PASSWORD_LENGTH:
        return redirect_with_notice(
            "/admin/users",
            f"Mật khẩu mới phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự",
        )

    account.name = clean_name
    if password_changed:
        account.password_hash = pwd.hash(clean_password)
        account.session_version += 1
    db.commit()
    response = RedirectResponse("/admin/users", 303)
    if account.id == user.id and password_changed:
        set_session_cookie(response, account)
    return response


@app.post("/admin/users/{account_id}/delete")
def delete_account(
    account_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_admin(user):
        raise HTTPException(403, "Chỉ quản trị viên được quản lý tài khoản")
    account = db.get(User, account_id)
    if not account or not admin_can_manage_account(user, account, db):
        raise HTTPException(404, "Không tìm thấy tài khoản trong phạm vi quản lý")
    if account.id == user.id:
        raise HTTPException(400, "Không thể xóa chính tài khoản đang đăng nhập")
    if db.scalar(select(Project.id).where(Project.owner_id == account.id)) is not None:
        raise HTTPException(
            400, "Không thể xóa tài khoản đang sở hữu bộ thời khóa biểu"
        )
    db.execute(
        delete(EmailChangeVerification).where(
            (EmailChangeVerification.user_id == account.id)
            | (EmailChangeVerification.requested_by_user_id == account.id)
        )
    )
    # Giữ lịch sử nguyện vọng nhưng không để lại user_id mồ côi sau khi
    # tài khoản bị xóa. submitted_name/submitted_email vẫn là snapshot để
    # quản trị viên biết nguyện vọng trước đây do ai gửi.
    preferences = db.scalars(
        select(TeacherPreference).where(
            TeacherPreference.submitted_by_user_id == account.id
        )
    ).all()
    for preference in preferences:
        preference.submitted_by_user_id = None
    db.delete(account)
    db.commit()
    return RedirectResponse("/admin/users", 303)


@app.post("/admin/users/{account_id}/promote-admin")
def promote_teacher_to_admin(
    account_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_super_admin(user):
        raise HTTPException(403, "Chỉ super admin được nâng giáo viên lên quản trị viên")
    account = db.get(User, account_id)
    if not account:
        raise HTTPException(404, "Không tìm thấy tài khoản")
    if account.role != "teacher":
        raise HTTPException(
            400, "Chỉ có thể nâng tài khoản giáo viên lên quản trị viên"
        )
    account.role = "admin"
    # Thay đổi quyền phải vô hiệu toàn bộ cookie phiên cũ của tài khoản giáo viên.
    account.session_version += 1
    db.commit()
    return RedirectResponse("/admin/users", 303)


@app.get("/projects", response_class=HTMLResponse)
def projects(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if user.role == "teacher":
        return RedirectResponse("/teacher", 303)
    if not is_admin(user):
        return RedirectResponse("/logout", 303)
    project_query = select(Project)
    assigned_schools = user_schools(user, db)
    if not is_super_admin(user):
        school_ids = {school.id for school in assigned_schools}
        if school_ids:
            project_query = project_query.where(Project.school_id.in_(school_ids))
        else:
            project_query = project_query.where(Project.id == -1)
    rows = db.scalars(project_query.order_by(Project.id.desc())).all()
    return templates.TemplateResponse(
        "projects.html",
        {
            "request": request,
            "user": user,
            "greeting_name": user_greeting_name(user),
            "projects": rows,
            "assigned_schools": assigned_schools,
            **chatbot_ui_context(rows[0] if rows else None),
        },
    )


@app.post("/projects")
def create_project(
    name: str = Form(""),
    school_name: str = Form(""),
    school_id: Optional[str] = Form(None),
    days: str = Form("6"),
    sessions: str = Form("2"),
    periods: str = Form("5"),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_admin(user):
        raise HTTPException(403)
    try:
        clean_name = bounded_text(name, "Tên bộ thời khóa biểu", 200)
    except HTTPException as exc:
        return redirect_with_notice(
            "/projects", str(exc.detail), open_create=1
        )

    if school_id not in (None, ""):
        try:
            parsed_school_id = int(school_id)
        except (TypeError, ValueError):
            return redirect_with_notice(
                "/projects", "Trường được chọn không hợp lệ", open_create=1
            )
        school = db.get(School, parsed_school_id)
        if not school or not user_can_access_school(user, school.id, db):
            return redirect_with_notice(
                "/projects",
                "Bạn không có quyền tạo thời khóa biểu cho trường này",
                open_create=1,
            )
        clean_school_name = school.name
    elif is_super_admin(user) and school_name.strip():
        # Giữ tương thích với form/client cũ; giao diện hiện tại tạo trường tại
        # Quản lý tài khoản rồi chọn trường khi tạo thời khóa biểu.
        school = ensure_school_for_name(db, school_name.strip())
        clean_school_name = school.name
    else:
        return redirect_with_notice(
            "/projects",
            "Tài khoản chưa được gán trường để tạo thời khóa biểu",
            open_create=1,
        )

    try:
        validated_days = bounded_int(days, 6, 5, 7, "Số ngày học")
        validated_sessions = bounded_int(sessions, 2, 1, 2, "Số buổi mỗi ngày")
        validated_periods = bounded_int(periods, 5, 1, 8, "Số tiết mỗi buổi")
    except HTTPException as exc:
        return redirect_with_notice(
            "/projects", str(exc.detail), open_create=1
        )
    p = Project(
        owner_id=user.id,
        school_id=school.id,
        name=clean_name,
        school_name=clean_school_name,
        days=validated_days,
        sessions=validated_sessions,
        periods_per_session=validated_periods,
    )
    db.add(p)
    db.commit()
    return RedirectResponse(f"/projects/{p.id}", 303)


def validate_clone_source(db: Session, pid: int) -> dict[str, list]:
    """Kiểm tra các tham chiếu nội bộ trước khi nhân bản project.

    Clone phải là thao tác all-or-nothing: nếu dữ liệu nguồn có tham chiếu chéo
    project hoặc dữ liệu legacy bị mồ côi thì dừng bằng HTTP 409, thay vì tạo
    một bản sao thiếu dữ liệu hoặc phát sinh KeyError/500 giữa transaction.
    """
    rows = {
        "departments": db.scalars(
            select(Department).where(Department.project_id == pid)
        ).all(),
        "subjects": db.scalars(select(Subject).where(Subject.project_id == pid)).all(),
        "teachers": db.scalars(select(Teacher).where(Teacher.project_id == pid)).all(),
        "teacher_subjects": db.scalars(
            select(TeacherSubject).where(TeacherSubject.project_id == pid)
        ).all(),
        "grades": db.scalars(select(Grade).where(Grade.project_id == pid)).all(),
        "grade_requirements": db.scalars(
            select(GradeSubjectRequirement).where(
                GradeSubjectRequirement.project_id == pid
            )
        ).all(),
        "classes": db.scalars(
            select(SchoolClass).where(SchoolClass.project_id == pid)
        ).all(),
        "assignments": db.scalars(
            select(Assignment).where(Assignment.project_id == pid)
        ).all(),
        "fixed_lessons": db.scalars(
            select(FixedLesson).where(FixedLesson.project_id == pid)
        ).all(),
        "lessons": db.scalars(select(Lesson).where(Lesson.project_id == pid)).all(),
    }

    department_ids = {row.id for row in rows["departments"]}
    subject_ids = {row.id for row in rows["subjects"]}
    teacher_ids = {row.id for row in rows["teachers"]}
    grade_ids = {row.id for row in rows["grades"]}
    class_ids = {row.id for row in rows["classes"]}
    assignment_ids = {row.id for row in rows["assignments"]}
    errors = []

    invalid_teacher_ids = [
        row.id
        for row in rows["teachers"]
        if row.department_id is not None and row.department_id not in department_ids
    ]
    if invalid_teacher_ids:
        errors.append(f"giáo viên có tổ chuyên môn không hợp lệ: {invalid_teacher_ids}")

    invalid_teacher_subject_ids = [
        row.id
        for row in rows["teacher_subjects"]
        if row.teacher_id not in teacher_ids or row.subject_id not in subject_ids
    ]
    if invalid_teacher_subject_ids:
        errors.append(
            f"quan hệ giáo viên-môn học không hợp lệ: {invalid_teacher_subject_ids}"
        )

    invalid_requirement_ids = [
        row.id
        for row in rows["grade_requirements"]
        if row.grade_id not in grade_ids or row.subject_id not in subject_ids
    ]
    if invalid_requirement_ids:
        errors.append(f"chương trình khối không hợp lệ: {invalid_requirement_ids}")

    invalid_class_ids = [
        row.id
        for row in rows["classes"]
        if row.grade_id is not None and row.grade_id not in grade_ids
    ]
    if invalid_class_ids:
        errors.append(f"lớp có khối không hợp lệ: {invalid_class_ids}")

    invalid_assignment_ids = [
        row.id
        for row in rows["assignments"]
        if row.class_id not in class_ids
        or row.subject_id not in subject_ids
        or row.teacher_id not in teacher_ids
    ]
    if invalid_assignment_ids:
        errors.append(f"phân công không hợp lệ: {invalid_assignment_ids}")

    invalid_fixed_lesson_ids = [
        row.id
        for row in rows["fixed_lessons"]
        if row.assignment_id not in assignment_ids
    ]
    if invalid_fixed_lesson_ids:
        errors.append(f"tiết cố định không hợp lệ: {invalid_fixed_lesson_ids}")

    invalid_lesson_ids = [
        row.id for row in rows["lessons"] if row.assignment_id not in assignment_ids
    ]
    if invalid_lesson_ids:
        errors.append(f"tiết học không hợp lệ: {invalid_lesson_ids}")

    if errors:
        raise HTTPException(
            409,
            "Không thể nhân bản vì project nguồn có dữ liệu không hợp lệ: "
            + " | ".join(errors),
        )
    return rows


@app.post("/projects/{pid}/rename")
def rename_project(
    pid: int,
    name: str = Form(""),
    return_to: str = Form("projects"),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    destination = f"/projects/{pid}" if return_to == "workspace" else "/projects"
    try:
        clean_name = bounded_text(name, "Tên bộ thời khóa biểu", 200)
    except HTTPException as exc:
        extra = {"open_rename": 1}
        if destination == "/projects":
            extra["rename_project_id"] = pid
        return redirect_with_notice(
            destination,
            str(exc.detail),
            **extra,
        )

    if project.name == clean_name:
        return redirect_with_notice(
            destination,
            "Tên bộ thời khóa biểu không thay đổi",
            kind="info",
        )

    project.name = clean_name
    db.commit()
    return redirect_with_notice(
        destination,
        "Đã đổi tên bộ thời khóa biểu",
        kind="success",
    )


@app.post("/projects/{pid}/clone")
def clone_project(
    pid: int,
    name: str | None = Form(None),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    # Dùng cùng khóa với mọi API chỉnh sửa để bản sao luôn được đọc từ một
    # trạng thái nhất quán, không trộn dữ liệu trước và sau một thay đổi đồng thời.
    src = get_project_for_update(pid, user, db)
    rows = validate_clone_source(db, pid)

    suffix = " (bản sao)"
    if name is None:
        clone_name = src.name[: 200 - len(suffix)] + suffix
    else:
        clone_name = name.strip()
        if not clone_name:
            raise HTTPException(400, "Tên bộ thời khóa biểu không được để trống")
        if len(clone_name) > 200:
            raise HTTPException(
                400, "Tên bộ thời khóa biểu không được vượt quá 200 ký tự"
            )

    p = Project(
        owner_id=user.id,
        school_id=src.school_id,
        name=clone_name,
        school_name=src.school_name,
        days=src.days,
        sessions=src.sessions,
        periods_per_session=src.periods_per_session,
        blocked_slots_json=src.blocked_slots_json,
    )
    db.add(p)
    db.flush()

    maps = {"dep": {}, "sub": {}, "tea": {}, "grade": {}, "cls": {}, "ass": {}}
    for x in rows["departments"]:
        n = Department(project_id=p.id, name=x.name)
        db.add(n)
        db.flush()
        maps["dep"][x.id] = n.id
    for x in rows["subjects"]:
        n = Subject(
            project_id=p.id,
            name=x.name,
            short_name=x.short_name,
            max_consecutive=x.max_consecutive,
        )
        db.add(n)
        db.flush()
        maps["sub"][x.id] = n.id
    for x in rows["teachers"]:
        n = Teacher(
            project_id=p.id,
            department_id=maps["dep"].get(x.department_id),
            name=x.name,
            short_name=x.short_name,
            max_periods_day=x.max_periods_day,
            unavailable_json=x.unavailable_json,
        )
        db.add(n)
        db.flush()
        maps["tea"][x.id] = n.id
    # Tài khoản giáo viên là người xem toàn cục nên project bản sao tự động
    # xuất hiện trong cổng giáo viên; không còn khái niệm sao chép quyền liên kết.
    for x in rows["teacher_subjects"]:
        db.add(
            TeacherSubject(
                project_id=p.id,
                teacher_id=maps["tea"][x.teacher_id],
                subject_id=maps["sub"][x.subject_id],
            )
        )
    # Nguyện vọng là lịch sử tham khảo nên không sao chép sang project mới.
    for x in rows["grades"]:
        n = Grade(project_id=p.id, name=x.name)
        db.add(n)
        db.flush()
        maps["grade"][x.id] = n.id
    for x in rows["grade_requirements"]:
        db.add(
            GradeSubjectRequirement(
                project_id=p.id,
                grade_id=maps["grade"][x.grade_id],
                subject_id=maps["sub"][x.subject_id],
                periods_per_week=x.periods_per_week,
                block_mode=x.block_mode,
            )
        )
    for x in rows["classes"]:
        n = SchoolClass(
            project_id=p.id,
            grade_id=maps["grade"].get(x.grade_id),
            name=x.name,
            unavailable_json=x.unavailable_json,
        )
        db.add(n)
        db.flush()
        maps["cls"][x.id] = n.id
    for x in rows["assignments"]:
        n = Assignment(
            project_id=p.id,
            class_id=maps["cls"][x.class_id],
            subject_id=maps["sub"][x.subject_id],
            teacher_id=maps["tea"][x.teacher_id],
            periods_per_week=x.periods_per_week,
            block_mode=x.block_mode,
            consecutive_pattern="",
        )
        db.add(n)
        db.flush()
        maps["ass"][x.id] = n.id
    for x in rows["fixed_lessons"]:
        db.add(
            FixedLesson(
                project_id=p.id,
                assignment_id=maps["ass"][x.assignment_id],
                slot=x.slot,
                group_size=x.group_size,
            )
        )
    for x in rows["lessons"]:
        db.add(
            Lesson(
                project_id=p.id,
                assignment_id=maps["ass"][x.assignment_id],
                slot=x.slot,
                locked=x.locked,
            )
        )
    db.commit()
    return RedirectResponse(f"/projects/{p.id}", 303)


@app.post("/projects/{pid}/delete")
def delete_project(
    pid: int, user: User = Depends(current_user), db: Session = Depends(db_session)
):
    project = get_project_for_update(pid, user, db)

    # Xóa theo thứ tự phụ thuộc khóa ngoại để toàn bộ dữ liệu của bộ TKB
    # được dọn sạch trong cùng một transaction.
    for model in (
        Lesson,
        FixedLesson,
        TeacherSubject,
        GradeSubjectRequirement,
        Assignment,
        TeacherPreference,
        SchoolClass,
        Teacher,
        Subject,
        Grade,
        Department,
    ):
        db.execute(delete(model).where(model.project_id == pid))

    # Log chatbot không có khóa ngoại tới projects, nhưng vẫn dọn theo project
    # để không giữ lại dữ liệu mồ côi sau khi bộ TKB đã bị xóa.
    db.execute(delete(ChatbotErrorLog).where(ChatbotErrorLog.project_id == pid))
    db.delete(project)
    db.commit()
    return RedirectResponse("/projects", 303)


@app.get("/schedule-audit", response_class=HTMLResponse)
def standalone_schedule_audit_page(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    chatbot_project = chatbot_project_for_user(user, db)
    return templates.TemplateResponse(
        "schedule_audit.html",
        {
            "request": request,
            "user": user,
            "days": DAYS,
            "ai_enabled": bool(os.getenv("GEMINI_API_KEY", "").strip()),
            "ai_primary_model": os.getenv("GEMINI_MODEL", "gemini-3.7-flash").strip()
            or "gemini-3.7-flash",
            **chatbot_ui_context(chatbot_project),
        },
    )


@app.get("/projects/{pid}/schedule-audit")
def legacy_schedule_audit_page(pid: int, user: User = Depends(current_user)):
    # Route cu chi de bookmark cu khong bi loi; khong doc bat ky du lieu project nao.
    return RedirectResponse("/schedule-audit", 303)


@app.get("/projects/{pid}", response_class=HTMLResponse)
def project_page(
    pid: int,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    p = get_project(pid, user, db)
    data = project_data(db, p)
    return templates.TemplateResponse(
        "workspace.html",
        {
            "request": request,
            "user": user,
            "p": p,
            "data": data,
            "days": DAYS,
            "public_base_url": public_base_url(request)
            or str(request.base_url).rstrip("/"),
            **chatbot_ui_context(p),
        },
    )


def read_schedule_upload(file: UploadFile) -> tuple[str, bytes]:
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(400, "Hãy chọn file thời khóa biểu cần kiểm tra.")
    content = file.file.read(MAX_SCHEDULE_AUDIT_FILE_BYTES + 1)
    if not content:
        raise HTTPException(400, "File tải lên đang rỗng.")
    if len(content) > MAX_SCHEDULE_AUDIT_FILE_BYTES:
        raise HTTPException(413, "File quá lớn. Giới hạn kiểm tra là 15 MB.")
    return filename, content


def read_schedule_audit_report_json(report_json: str) -> dict:
    raw = str(report_json or "").strip()
    if not raw:
        raise HTTPException(400, "Thiếu dữ liệu thời khóa biểu đã chỉnh sửa.")
    if len(raw.encode("utf-8")) > MAX_SCHEDULE_AUDIT_FILE_BYTES:
        raise HTTPException(
            413, "Dữ liệu thời khóa biểu đã chỉnh sửa vượt quá giới hạn 15 MB."
        )
    try:
        report = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            400, "Dữ liệu thời khóa biểu đã chỉnh sửa không hợp lệ."
        ) from exc
    if not isinstance(report, dict) or report.get("ok") is not True:
        raise HTTPException(400, "Dữ liệu thời khóa biểu đã chỉnh sửa không hợp lệ.")
    viewer = report.get("viewer")
    if not isinstance(viewer, dict) or not isinstance(viewer.get("cells"), list):
        raise HTTPException(400, "Dữ liệu thời khóa biểu đã chỉnh sửa thiếu bảng lịch.")
    cells = viewer["cells"]
    if len(cells) > 50000:
        raise HTTPException(413, "Thời khóa biểu có quá nhiều ô để phân tích bằng AI.")
    try:
        days = int(viewer.get("days") or 0)
        sessions = int(viewer.get("sessions") or 0)
        periods = int(viewer.get("periods") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            400, "Kích thước thời khóa biểu đã chỉnh sửa không hợp lệ."
        ) from exc
    if not (1 <= days <= 7 and 1 <= sessions <= 4 and 1 <= periods <= 20):
        raise HTTPException(400, "Kích thước thời khóa biểu đã chỉnh sửa không hợp lệ.")
    from app.schedule_audit import recalculate_standalone_edited_report

    try:
        return recalculate_standalone_edited_report(report)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            400, "Dữ liệu thời khóa biểu đã chỉnh sửa không hợp lệ."
        ) from exc


@app.post("/api/schedule-audit")
def standalone_audit_schedule_file(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
):
    filename, content = read_schedule_upload(file)
    from app.schedule_audit import (
        ScheduleAuditParseError,
        analyze_standalone_schedule_file,
    )

    try:
        return analyze_standalone_schedule_file(
            filename=filename,
            content=content,
            include_editable=False,
        )
    except ScheduleAuditParseError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
    except Exception:
        logger.exception("standalone schedule audit failed")
        return JSONResponse(
            {
                "ok": False,
                "message": "Không thể phân tích file thời khóa biểu này. Hãy kiểm tra lại cấu trúc file.",
            },
            status_code=500,
        )


@app.post("/api/schedule-audit/ai")
def standalone_ai_audit_schedule_file(
    file: Optional[UploadFile] = File(None),
    report_json: str = Form(""),
    user: User = Depends(current_user),
):
    from app.chatbot import ChatbotError
    from app.schedule_ai import analyze_schedule_with_gemini
    from app.schedule_audit import (
        ScheduleAuditParseError,
        analyze_standalone_schedule_file,
        apply_standalone_viewer_edits,
    )

    if report_json.strip():
        edited_report = read_schedule_audit_report_json(report_json)
        if file is not None:
            filename, content = read_schedule_upload(file)
            try:
                base_report = analyze_standalone_schedule_file(
                    filename=filename,
                    content=content,
                    include_editable=False,
                )
                report = apply_standalone_viewer_edits(base_report, edited_report)
            except ScheduleAuditParseError as exc:
                return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
            except ValueError:
                return JSONResponse(
                    {
                        "ok": False,
                        "message": "Dữ liệu chỉnh sửa không khớp với file thời khóa biểu gốc.",
                    },
                    status_code=400,
                )
            except Exception:
                logger.exception("standalone AI edited schedule rebuild failed")
                return JSONResponse(
                    {
                        "ok": False,
                        "message": "Không thể đối chiếu dữ liệu chỉnh sửa với file thời khóa biểu gốc.",
                    },
                    status_code=500,
                )
        else:
            # Backward-compatible fallback for older clients. Derived fields are
            # still recomputed by read_schedule_audit_report_json().
            report = edited_report
    else:
        if file is None:
            return JSONResponse(
                {"ok": False, "message": "Hãy chọn file thời khóa biểu cần phân tích."},
                status_code=400,
            )
        filename, content = read_schedule_upload(file)
        try:
            report = analyze_standalone_schedule_file(
                filename=filename,
                content=content,
                include_editable=False,
            )
        except ScheduleAuditParseError as exc:
            return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
        except Exception:
            logger.exception("standalone AI schedule audit parse failed")
            return JSONResponse(
                {
                    "ok": False,
                    "message": "Không thể đọc file thời khóa biểu trước khi gửi sang AI.",
                },
                status_code=500,
            )

    try:
        ai_result, model_used, fallback_failures = analyze_schedule_with_gemini(report)
        return {
            "ok": True,
            "report": report,
            "ai": ai_result,
            "model": model_used,
            "fallback_failures": fallback_failures,
        }
    except ChatbotError as exc:
        logger.warning("AI schedule audit failed: %s", exc)
        status_code = 400 if exc.code == "context_too_large" else 503
        return JSONResponse(
            {
                "ok": False,
                "message": str(exc),
                "code": exc.code,
            },
            status_code=status_code,
        )
    except Exception:
        logger.exception("unexpected AI schedule audit failure")
        return JSONResponse(
            {
                "ok": False,
                "message": "Không thể kết nối AI để phân tích thời khóa biểu. Kiểm tra thường vẫn hoạt động bình thường.",
            },
            status_code=503,
        )


@app.get("/projects/{pid}/chatbot", response_class=HTMLResponse)
def chatbot_page(
    pid: int,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    p, _ = chatbot_project_data_for_user(pid, user, db)
    return templates.TemplateResponse(
        "chatbot.html",
        {
            "request": request,
            "user": user,
            "p": p,
            **chatbot_ui_context(p),
        },
    )


@app.post("/api/projects/{pid}/chatbot")
def chatbot_reply(
    pid: int,
    message: str = Form(...),
    history_json: str = Form("[]"),
    document_context_json: str = Form("[]"),
    preferred_model: str = Form(""),
    files: list[UploadFile] | None = File(None),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    from app.chatbot import (
        MAX_TOTAL_UPLOAD_BYTES,
        MAX_UPLOAD_BYTES,
        MAX_UPLOAD_FILES,
        ChatbotError,
        ask_gemini,
        parse_uploaded_table,
    )

    p, chatbot_data = chatbot_project_data_for_user(pid, user, db)
    clean_message = message.strip()
    if not clean_message:
        raise HTTPException(400, "Hãy nhập nội dung cần tư vấn")
    if len(clean_message) > 4000:
        raise HTTPException(400, "Nội dung không được vượt quá 4.000 ký tự")
    try:
        raw_history = json.loads(history_json)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(400, "Lịch sử trò chuyện không hợp lệ")
    if not isinstance(raw_history, list):
        raise HTTPException(400, "Lịch sử trò chuyện không hợp lệ")
    history = []
    for item in raw_history[-8:]:
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
            continue
        content = str(item.get("content", "")).strip()
        if content:
            history.append({"role": item["role"], "content": content[:8000]})

    if len(document_context_json) > MAX_CHATBOT_DOCUMENT_CONTEXT_CHARS:
        raise HTTPException(
            400,
            "Ngữ cảnh tệp của cuộc trò chuyện quá lớn. Hãy xóa cuộc trò chuyện và đính kèm lại tệp cần dùng.",
        )
    try:
        retained_documents = json.loads(document_context_json)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(400, "Ngữ cảnh tệp của cuộc trò chuyện không hợp lệ")
    if not isinstance(retained_documents, list) or any(
        not isinstance(item, dict) for item in retained_documents
    ):
        raise HTTPException(400, "Ngữ cảnh tệp của cuộc trò chuyện không hợp lệ")

    upload_items = [item for item in (files or []) if item.filename]
    if len(upload_items) > MAX_UPLOAD_FILES:
        raise HTTPException(400, f"Chỉ được đính kèm tối đa {MAX_UPLOAD_FILES} tệp")
    uploaded_tables = []
    total_upload_bytes = 0
    for file in upload_items:
        content = file.file.read(MAX_UPLOAD_BYTES + 1)
        total_upload_bytes += len(content)
        if total_upload_bytes > MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(400, "Tổng dung lượng tệp vượt quá giới hạn 12 MB")
        try:
            uploaded_tables.append(parse_uploaded_table(file.filename, content))
        except ChatbotError as exc:
            raise HTTPException(400, str(exc))

    document_map = {}
    for document in [*retained_documents, *uploaded_tables]:
        filename = str(document.get("filename", "")).strip()[:200]
        document_type = str(document.get("type", "")).strip()[:20]
        if not filename or not document_type:
            continue
        document_map[(filename, document_type)] = document
    document_context = list(document_map.values())
    if (
        len(json.dumps(document_context, ensure_ascii=False, separators=(",", ":")))
        > MAX_CHATBOT_DOCUMENT_CONTEXT_CHARS
    ):
        raise HTTPException(
            400,
            "Ngữ cảnh tệp của cuộc trò chuyện quá lớn. Hãy xóa cuộc trò chuyện và chỉ đính kèm các tệp cần thiết.",
        )

    def persist_chatbot_failure(
        error_code: str, error_message: str, provider_status: int | None = None
    ) -> None:
        try:
            db.add(
                ChatbotErrorLog(
                    project_id=p.id,
                    project_name=p.name,
                    user_id=user.id,
                    user_name=user.name,
                    user_email=user.email,
                    error_code=error_code[:64],
                    provider_status=provider_status,
                    error_message=error_message[:8000],
                )
            )
            db.commit()
            cutoff_id = db.scalar(
                select(ChatbotErrorLog.id)
                .order_by(ChatbotErrorLog.id.desc())
                .offset(MAX_CHATBOT_ERROR_LOGS - 1)
                .limit(1)
            )
            if cutoff_id is not None:
                db.execute(
                    delete(ChatbotErrorLog).where(ChatbotErrorLog.id < cutoff_id)
                )
                db.commit()
        except Exception:
            db.rollback()
            logger.exception("Could not persist chatbot error log for project %s", pid)

    try:
        answer, model_used, fallback_failures = ask_gemini(
            clean_message,
            history,
            chatbot_data,
            document_context or None,
            preferred_model=preferred_model.strip() or None,
        )
        for failure in fallback_failures:
            persist_chatbot_failure(
                str(failure.get("code") or "chatbot_error"),
                f"[model={failure.get('model') or 'unknown'}] {failure.get('message') or ''}",
                failure.get("provider_status"),
            )
    except ChatbotError as exc:
        logger.warning("Chatbot request failed for project %s: %s", pid, exc)
        attempts = list(getattr(exc, "attempts", []) or [])
        if attempts:
            for failure in attempts:
                persist_chatbot_failure(
                    str(failure.get("code") or "chatbot_error"),
                    f"[model={failure.get('model') or 'unknown'}] {failure.get('message') or ''}",
                    failure.get("provider_status"),
                )
        else:
            model_name = getattr(exc, "model_name", None)
            prefix = f"[model={model_name}] " if model_name else ""
            persist_chatbot_failure(
                str(getattr(exc, "code", "chatbot_error")),
                f"{prefix}{exc}",
                getattr(exc, "provider_status", None),
            )
        raise HTTPException(503, "Không thể kết nối tới chatbot. Vui lòng thử lại sau.")
    except Exception as exc:
        logger.exception("Unexpected chatbot failure for project %s", pid)
        persist_chatbot_failure(
            "internal_error",
            f"{type(exc).__name__}: {exc}",
        )
        raise HTTPException(503, "Không thể kết nối tới chatbot. Vui lòng thử lại sau.")
    return {
        "answer": answer,
        "files_analyzed": len(uploaded_tables),
        "document_context": document_context,
        "model_used": model_used,
        "fallback_used": model_used
        != (
            os.getenv("GEMINI_MODEL", "gemini-3.7-flash").strip() or "gemini-3.7-flash"
        ),
    }


class EntityIn(BaseModel):
    type: str
    data: dict


class BulkAssignmentSubjectIn(BaseModel):
    subject_id: int
    periods_per_week: int = 1
    block_mode: str = "free"


class BulkAssignmentIn(BaseModel):
    teacher_id: int
    class_ids: list[int]
    subjects: list[BulkAssignmentSubjectIn] = Field(default_factory=list)
    # Tương thích với client cũ trong lúc nâng cấp. Giao diện mới dùng subjects.
    subject_ids: list[int] = Field(default_factory=list)
    periods_per_week: int = 1
    block_mode: str = "free"


def ensure_unique_project_name(
    db: Session,
    model,
    project_id: int,
    name: str,
    label: str,
    exclude_id: int | None = None,
) -> None:
    stmt = select(model.id).where(
        model.project_id == project_id,
        func.lower(model.name) == name.lower(),
    )
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise HTTPException(409, f"{label} ‘{name}’ đã tồn tại trong bộ thời khóa biểu")


def ensure_unique_teacher_short_name(
    db: Session,
    project_id: int,
    short_name: str,
    exclude_id: int | None = None,
) -> None:
    normalized = short_name.strip()
    stmt = select(Teacher.id).where(
        Teacher.project_id == project_id,
        func.lower(func.trim(Teacher.short_name)) == normalized.lower(),
    )
    if exclude_id is not None:
        stmt = stmt.where(Teacher.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise HTTPException(
            409,
            f"Tên ngắn giáo viên ‘{normalized}’ đã được sử dụng trong bộ thời khóa biểu",
        )


def validated_subject_ids(db: Session, project_id: int, values) -> list[int]:
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]
    result = []
    for value in values:
        try:
            subject_id = int(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                400, "Danh sách môn của giáo viên không hợp lệ"
            ) from exc
        if subject_id > 0 and subject_id not in result:
            result.append(subject_id)
    if not result:
        return []
    found = set(
        db.scalars(
            select(Subject.id).where(
                Subject.project_id == project_id,
                Subject.id.in_(result),
            )
        ).all()
    )
    if found != set(result):
        raise HTTPException(400, "Có môn học không thuộc bộ thời khóa biểu")
    return result


def replace_teacher_subjects(
    db: Session, project_id: int, teacher_id: int, subject_ids: list[int]
) -> None:
    rows = db.scalars(
        select(TeacherSubject).where(
            TeacherSubject.project_id == project_id,
            TeacherSubject.teacher_id == teacher_id,
        )
    ).all()
    existing = {row.subject_id: row for row in rows}
    wanted = set(subject_ids)
    for subject_id, row in existing.items():
        if subject_id not in wanted:
            db.delete(row)
    for subject_id in subject_ids:
        if subject_id not in existing:
            db.add(
                TeacherSubject(
                    project_id=project_id, teacher_id=teacher_id, subject_id=subject_id
                )
            )


def normalized_grade_requirements(
    db: Session, project: Project, values
) -> list[tuple[int, int, str]]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise HTTPException(400, "Chương trình môn của khối không hợp lệ")
    configs: dict[int, tuple[int, str]] = {}
    for item in values:
        if not isinstance(item, dict):
            raise HTTPException(400, "Chương trình môn của khối không hợp lệ")
        subject_id = required_id(item, "subject_id", "Môn học")
        subject = db.get(Subject, subject_id)
        if not subject or subject.project_id != project.id:
            raise HTTPException(400, "Có môn học không thuộc bộ thời khóa biểu")
        periods = bounded_int(
            item.get("periods_per_week"), 1, 1, 40, f"Số tiết/tuần của {subject.name}"
        )
        try:
            mode = normalized_block_mode(
                item.get("block_mode", "free"), periods, subject, project
            )
        except ValueError as exc:
            raise HTTPException(400, f"{subject.name}: {exc}") from exc
        configs[subject_id] = (periods, mode)
    return [
        (subject_id, periods, mode) for subject_id, (periods, mode) in configs.items()
    ]


def replace_grade_requirements(
    db: Session, project: Project, grade_id: int, values
) -> None:
    configs = normalized_grade_requirements(db, project, values)
    rows = db.scalars(
        select(GradeSubjectRequirement).where(
            GradeSubjectRequirement.project_id == project.id,
            GradeSubjectRequirement.grade_id == grade_id,
        )
    ).all()
    existing = {row.subject_id: row for row in rows}
    wanted = {subject_id for subject_id, _, _ in configs}
    for subject_id, row in existing.items():
        if subject_id not in wanted:
            db.delete(row)
    for subject_id, periods, mode in configs:
        row = existing.get(subject_id)
        if row is None:
            db.add(
                GradeSubjectRequirement(
                    project_id=project.id,
                    grade_id=grade_id,
                    subject_id=subject_id,
                    periods_per_week=periods,
                    block_mode=mode,
                )
            )
        else:
            row.periods_per_week = periods
            row.block_mode = mode


def teacher_week_capacity(
    project: Project,
    teacher: Teacher,
    max_periods_day: int | None = None,
    unavailable_slots: set[int] | None = None,
    project_blocked_slots: set[int] | None = None,
) -> int:
    daily_limit = (
        max_periods_day if max_periods_day is not None else teacher.max_periods_day
    )
    periods_per_day = project.sessions * project.periods_per_session
    project_blocked = (
        project_blocked_slots
        if project_blocked_slots is not None
        else set(
            valid_slots(
                project,
                parse_slots(project.blocked_slots_json),
                strict=False,
            )
        )
    )
    teacher_blocked = (
        parse_slots(teacher.unavailable_json)
        if unavailable_slots is None
        else set(unavailable_slots)
    )
    teacher_blocked = set(valid_slots(project, teacher_blocked, strict=False))
    capacity = 0
    for day in range(project.days):
        start = day * periods_per_day
        available = sum(
            1
            for slot in range(start, start + periods_per_day)
            if slot not in project_blocked and slot not in teacher_blocked
        )
        capacity += min(daily_limit, available)
    return capacity


def class_week_capacity(
    project: Project,
    school_class: SchoolClass,
    unavailable_slots: set[int] | None = None,
    project_blocked_slots: set[int] | None = None,
) -> int:
    maximum = project.days * project.sessions * project.periods_per_session
    project_blocked = (
        project_blocked_slots
        if project_blocked_slots is not None
        else set(
            valid_slots(
                project,
                parse_slots(project.blocked_slots_json),
                strict=False,
            )
        )
    )
    class_blocked = (
        parse_slots(school_class.unavailable_json)
        if unavailable_slots is None
        else unavailable_slots
    )
    class_blocked = set(valid_slots(project, class_blocked, strict=False))
    return maximum - len(project_blocked | class_blocked)


def teacher_assigned_periods(db: Session, project_id: int, teacher_id: int) -> int:
    value = db.scalar(
        select(func.coalesce(func.sum(Assignment.periods_per_week), 0)).where(
            Assignment.project_id == project_id,
            Assignment.teacher_id == teacher_id,
        )
    )
    return int(value or 0)


def class_assigned_periods(db: Session, project_id: int, class_id: int) -> int:
    value = db.scalar(
        select(func.coalesce(func.sum(Assignment.periods_per_week), 0)).where(
            Assignment.project_id == project_id,
            Assignment.class_id == class_id,
        )
    )
    return int(value or 0)


def ensure_teacher_load_fits(
    db: Session,
    project: Project,
    teacher: Teacher,
    projected_periods: int,
    max_periods_day: int | None = None,
    unavailable_slots: set[int] | None = None,
    project_blocked_slots: set[int] | None = None,
) -> None:
    capacity = teacher_week_capacity(
        project,
        teacher,
        max_periods_day=max_periods_day,
        unavailable_slots=unavailable_slots,
        project_blocked_slots=project_blocked_slots,
    )
    if projected_periods > capacity:
        raise HTTPException(
            409,
            f"Tải dạy của {teacher.name} sẽ là {projected_periods} tiết/tuần, "
            f"vượt khả năng tối đa hiện tại {capacity} tiết/tuần theo số ngày, "
            "tiết tránh và giới hạn tiết/ngày.",
        )


def ensure_class_load_fits(
    project: Project,
    school_class: SchoolClass,
    projected_periods: int,
    unavailable_slots: set[int] | None = None,
    project_blocked_slots: set[int] | None = None,
) -> None:
    capacity = class_week_capacity(
        project,
        school_class,
        unavailable_slots=unavailable_slots,
        project_blocked_slots=project_blocked_slots,
    )
    if projected_periods > capacity:
        raise HTTPException(
            409,
            f"Tải học của lớp {school_class.name} sẽ là {projected_periods} tiết/tuần, "
            f"vượt {capacity} ô có thể học theo khóa lịch và tiết tránh hiện tại.",
        )


def duplicate_assignment_issues(
    db: Session, assignments: list[Assignment]
) -> list[dict]:
    grouped = defaultdict(list)
    for assignment in assignments:
        grouped[(assignment.class_id, assignment.subject_id)].append(assignment)
    issues = []
    for (class_id, subject_id), rows in grouped.items():
        if len(rows) < 2:
            continue
        school_class = db.get(SchoolClass, class_id)
        subject = db.get(Subject, subject_id)
        teacher_names = []
        for row in rows:
            teacher = db.get(Teacher, row.teacher_id)
            teacher_names.append(
                teacher.name if teacher else f"Giáo viên #{row.teacher_id}"
            )
        issues.append(
            {
                "class_id": class_id,
                "class_name": school_class.name if school_class else f"Lớp #{class_id}",
                "subject_id": subject_id,
                "subject_name": subject.name if subject else f"Môn #{subject_id}",
                "assignment_ids": sorted(row.id for row in rows),
                "teacher_names": teacher_names,
            }
        )
    return sorted(issues, key=lambda item: (item["class_name"], item["subject_name"]))


def assignment_project_reference_issues(
    db: Session, project_id: int, assignments: list[Assignment]
) -> list[dict]:
    """Phát hiện phân công tham chiếu lớp/môn/GV mất hoặc thuộc project khác."""
    if not assignments:
        return []
    teacher_ids = {row.teacher_id for row in assignments}
    class_ids = {row.class_id for row in assignments}
    subject_ids = {row.subject_id for row in assignments}
    teacher_projects = (
        dict(
            db.execute(
                select(Teacher.id, Teacher.project_id).where(
                    Teacher.id.in_(teacher_ids)
                )
            ).all()
        )
        if teacher_ids
        else {}
    )
    class_projects = (
        dict(
            db.execute(
                select(SchoolClass.id, SchoolClass.project_id).where(
                    SchoolClass.id.in_(class_ids)
                )
            ).all()
        )
        if class_ids
        else {}
    )
    subject_projects = (
        dict(
            db.execute(
                select(Subject.id, Subject.project_id).where(
                    Subject.id.in_(subject_ids)
                )
            ).all()
        )
        if subject_ids
        else {}
    )

    specs = (
        ("teacher_id", "Giáo viên", teacher_projects),
        ("class_id", "Lớp", class_projects),
        ("subject_id", "Môn", subject_projects),
    )
    issues = []
    for assignment in assignments:
        invalid_refs = []
        for field, label, projects_by_id in specs:
            reference_id = getattr(assignment, field)
            actual_project_id = projects_by_id.get(reference_id)
            if actual_project_id != project_id:
                invalid_refs.append(
                    {
                        "field": field,
                        "label": label,
                        "id": reference_id,
                        "actual_project_id": actual_project_id,
                    }
                )
        if invalid_refs:
            issues.append(
                {
                    "assignment_id": assignment.id,
                    "invalid_refs": invalid_refs,
                }
            )
    return issues


def schedule_teacher_capacity_issues(
    db: Session,
    project: Project,
    assignments: list[Assignment],
) -> list[dict]:
    """Return teacher loads that cannot fit even before conflict solving.

    This necessary (but not sufficient) feasibility check also covers legacy
    and imported data that predates assignment-time load validation. It lets the
    scheduler explain the real constraint instead of appearing to skip teachers.
    """
    assigned_by_teacher = Counter()
    for assignment in assignments:
        assigned_by_teacher[assignment.teacher_id] += int(
            assignment.periods_per_week or 0
        )

    project_blocked = set(
        valid_slots(
            project,
            parse_slots(project.blocked_slots_json),
            strict=False,
        )
    )
    issues = []
    for teacher_id, assigned in assigned_by_teacher.items():
        teacher = db.get(Teacher, teacher_id)
        if not teacher:
            continue
        capacity = teacher_week_capacity(
            project,
            teacher,
            project_blocked_slots=project_blocked,
        )
        if assigned > capacity:
            issues.append(
                {
                    "teacher_id": teacher.id,
                    "teacher_name": teacher.name,
                    "assigned": assigned,
                    "capacity": capacity,
                    "excess": assigned - capacity,
                }
            )
    return sorted(issues, key=lambda item: (-item["excess"], item["teacher_name"]))


def schedule_class_capacity_issues(
    project: Project,
    classes: list[SchoolClass],
    assignments: list[Assignment],
) -> list[dict]:
    assigned_by_class = Counter()
    for assignment in assignments:
        assigned_by_class[assignment.class_id] += int(assignment.periods_per_week or 0)
    issues = []
    for school_class in classes:
        assigned = assigned_by_class[school_class.id]
        if not assigned:
            continue
        capacity = class_week_capacity(project, school_class)
        if assigned > capacity:
            issues.append(
                {
                    "class_id": school_class.id,
                    "class_name": school_class.name,
                    "assigned": assigned,
                    "capacity": capacity,
                    "excess": assigned - capacity,
                }
            )
    return sorted(issues, key=lambda item: (-item["excess"], item["class_name"]))


def grade_requirement_assignment_issues(
    db: Session,
    project: Project,
    assignments: list[Assignment] | None = None,
    classes: list[SchoolClass] | None = None,
) -> list[dict]:
    """Return missing/mismatched class-subject assignments for configured grade curricula."""
    requirements = db.scalars(
        select(GradeSubjectRequirement).where(
            GradeSubjectRequirement.project_id == project.id,
        )
    ).all()
    if not requirements:
        return []
    if assignments is None:
        assignments = db.scalars(
            select(Assignment).where(Assignment.project_id == project.id)
        ).all()
    if classes is None:
        classes = db.scalars(
            select(SchoolClass).where(SchoolClass.project_id == project.id)
        ).all()

    requirement_by_grade = defaultdict(list)
    for requirement in requirements:
        requirement_by_grade[requirement.grade_id].append(requirement)
    assignment_by_pair = {(row.class_id, row.subject_id): row for row in assignments}
    subject_ids = {row.subject_id for row in requirements}
    subjects = (
        {
            row.id: row
            for row in db.scalars(
                select(Subject).where(
                    Subject.project_id == project.id,
                    Subject.id.in_(subject_ids),
                )
            ).all()
        }
        if subject_ids
        else {}
    )
    grade_ids = {row.grade_id for row in requirements}
    grades = (
        {
            row.id: row
            for row in db.scalars(
                select(Grade).where(
                    Grade.project_id == project.id,
                    Grade.id.in_(grade_ids),
                )
            ).all()
        }
        if grade_ids
        else {}
    )

    issues: list[dict] = []
    for school_class in classes:
        if school_class.grade_id is None:
            continue
        for requirement in requirement_by_grade.get(school_class.grade_id, []):
            assignment = assignment_by_pair.get(
                (school_class.id, requirement.subject_id)
            )
            subject = subjects.get(requirement.subject_id)
            grade = grades.get(school_class.grade_id)
            base = {
                "class_id": school_class.id,
                "class_name": school_class.name,
                "grade_id": school_class.grade_id,
                "grade_name": grade.name if grade else "?",
                "subject_id": requirement.subject_id,
                "subject_name": subject.name if subject else "?",
                "required_periods": int(requirement.periods_per_week),
                "required_mode": requirement.block_mode or "free",
            }
            if assignment is None:
                issues.append({**base, "issue_type": "missing"})
                continue
            actual_periods = int(assignment.periods_per_week)
            actual_mode = assignment.block_mode or "free"
            if actual_periods != int(requirement.periods_per_week) or actual_mode != (
                requirement.block_mode or "free"
            ):
                issues.append(
                    {
                        **base,
                        "issue_type": "mismatch",
                        "assignment_id": assignment.id,
                        "assigned_periods": actual_periods,
                        "assigned_mode": actual_mode,
                    }
                )
    issues.sort(key=lambda item: (item["class_name"], item["subject_name"]))
    return issues


def block_mode_text(mode: str) -> str:
    return {
        "free": "Tự do",
        "preferred_double": "Ưu tiên tiết đôi",
        "required_double": "Bắt buộc tiết đôi",
    }.get(mode or "free", mode or "Tự do")


def grade_requirement_for_assignment(
    db: Session,
    project_id: int,
    school_class: SchoolClass,
    subject_id: int,
) -> GradeSubjectRequirement | None:
    if school_class.grade_id is None:
        return None
    return db.scalar(
        select(GradeSubjectRequirement).where(
            GradeSubjectRequirement.project_id == project_id,
            GradeSubjectRequirement.grade_id == school_class.grade_id,
            GradeSubjectRequirement.subject_id == subject_id,
        )
    )


def ensure_assignment_matches_grade_requirement(
    db: Session,
    project: Project,
    school_class: SchoolClass,
    subject: Subject,
    periods: int,
    mode: str,
) -> None:
    requirement = grade_requirement_for_assignment(
        db, project.id, school_class, subject.id
    )
    if requirement is None:
        return
    required_periods = int(requirement.periods_per_week)
    required_mode = requirement.block_mode or "free"
    if periods == required_periods and mode == required_mode:
        return
    grade = db.get(Grade, school_class.grade_id) if school_class.grade_id else None
    raise HTTPException(
        409,
        f"{school_class.name} – {subject.name} phải khớp chương trình "
        f"{grade.name if grade else 'khối'}: {required_periods} tiết/tuần · "
        f"{block_mode_text(required_mode)}. Dữ liệu đang nhập là "
        f"{periods} tiết/tuần · {block_mode_text(mode)}.",
    )


def grade_requirement_missing_assignments(
    db: Session,
    project: Project,
    grade_id: int,
    configs: list[tuple[int, int, str]],
    classes: list[SchoolClass] | None = None,
) -> list[str]:
    """Trả về các môn bắt buộc chưa có phân công cho từng lớp.

    Các phân công đã tồn tại nhưng khác số tiết/chế độ sẽ được đồng bộ nguyên tử
    bởi ``sync_assignments_to_grade_requirements``. Chỉ trường hợp chưa có
    phân công mới cần người dùng chọn giáo viên trước.
    """
    if classes is None:
        classes = db.scalars(
            select(SchoolClass).where(
                SchoolClass.project_id == project.id,
                SchoolClass.grade_id == grade_id,
            )
        ).all()
    if not classes or not configs:
        return []
    class_ids = [row.id for row in classes]
    subject_ids = [subject_id for subject_id, _, _ in configs]
    assignments = db.scalars(
        select(Assignment).where(
            Assignment.project_id == project.id,
            Assignment.class_id.in_(class_ids),
            Assignment.subject_id.in_(subject_ids),
        )
    ).all()
    assigned_pairs = {(row.class_id, row.subject_id) for row in assignments}
    subjects = {
        row.id: row
        for row in db.scalars(
            select(Subject).where(
                Subject.project_id == project.id,
                Subject.id.in_(subject_ids),
            )
        ).all()
    }
    issues: list[str] = []
    for school_class in classes:
        for subject_id, required_periods, required_mode in configs:
            if (school_class.id, subject_id) in assigned_pairs:
                continue
            subject = subjects.get(subject_id)
            subject_name = subject.name if subject else f"môn #{subject_id}"
            issues.append(
                f"{school_class.name} – {subject_name}: thiếu phân công "
                f"{required_periods} tiết/tuần · {block_mode_text(required_mode)}"
            )
    return issues


def sync_assignments_to_grade_requirements(
    db: Session,
    project: Project,
    grade_id: int,
    configs: list[tuple[int, int, str]],
    classes: list[SchoolClass] | None = None,
) -> int:
    """Đồng bộ phân công hiện có với chương trình khối trong cùng transaction.

    Hàm không tự tạo phân công vì không thể tự chọn giáo viên. Các thay đổi tải
    dạy/tải học được kiểm tra theo tổng delta trước khi sửa ORM objects; các
    ghim và tính khả thi của lịch hiện tại cũng được kiểm tra trước khi commit.
    """
    if classes is None:
        classes = db.scalars(
            select(SchoolClass).where(
                SchoolClass.project_id == project.id,
                SchoolClass.grade_id == grade_id,
            )
        ).all()
    if not classes or not configs:
        return 0

    class_by_id = {row.id: row for row in classes}
    class_ids = list(class_by_id)
    config_by_subject = {
        subject_id: (int(periods), mode or "free")
        for subject_id, periods, mode in configs
    }
    subject_ids = list(config_by_subject)
    assignments = db.scalars(
        select(Assignment).where(
            Assignment.project_id == project.id,
            Assignment.class_id.in_(class_ids),
            Assignment.subject_id.in_(subject_ids),
        )
    ).all()
    if not assignments:
        return 0

    subjects = {
        row.id: row
        for row in db.scalars(
            select(Subject).where(
                Subject.project_id == project.id,
                Subject.id.in_(subject_ids),
            )
        ).all()
    }
    teacher_ids = {row.teacher_id for row in assignments}
    teachers = {
        row.id: row
        for row in db.scalars(
            select(Teacher).where(
                Teacher.project_id == project.id,
                Teacher.id.in_(teacher_ids),
            )
        ).all()
    }

    changes = []
    teacher_deltas: Counter[int] = Counter()
    class_deltas: Counter[int] = Counter()
    for assignment in assignments:
        desired = config_by_subject.get(assignment.subject_id)
        if desired is None:
            continue
        periods, mode = desired
        old_periods = int(assignment.periods_per_week)
        old_mode = assignment.block_mode or "free"
        if old_periods == periods and old_mode == mode:
            continue

        school_class = class_by_id.get(assignment.class_id)
        subject = subjects.get(assignment.subject_id)
        teacher = teachers.get(assignment.teacher_id)
        if not school_class or not subject or not teacher:
            raise HTTPException(
                409,
                "Không thể đồng bộ chương trình khối vì có phân công tham chiếu dữ liệu không còn tồn tại.",
            )

        lessons = db.scalars(
            select(Lesson).where(Lesson.assignment_id == assignment.id)
        ).all()
        scheduled = len(lessons)
        if periods < scheduled:
            raise HTTPException(
                409,
                f"Không thể đổi chương trình: {school_class.name} – {subject.name} "
                f"đang có {scheduled} tiết trên lịch nhưng chuẩn mới chỉ còn {periods} tiết/tuần. "
                "Hãy gỡ bớt tiết trên lịch trước.",
            )

        ensure_required_double_hard_feasible(
            project, teacher, school_class, subject, periods, mode
        )
        delta = periods - old_periods
        teacher_deltas[teacher.id] += delta
        class_deltas[school_class.id] += delta
        changes.append(
            (
                assignment,
                school_class,
                subject,
                teacher,
                lessons,
                periods,
                mode,
                old_periods,
                old_mode,
            )
        )

    for teacher_id, delta in teacher_deltas.items():
        teacher = teachers[teacher_id]
        ensure_teacher_load_fits(
            db,
            project,
            teacher,
            teacher_assigned_periods(db, project.id, teacher_id) + delta,
        )
    for class_id, delta in class_deltas.items():
        school_class = class_by_id[class_id]
        ensure_class_load_fits(
            project,
            school_class,
            class_assigned_periods(db, project.id, class_id) + delta,
        )

    for (
        assignment,
        school_class,
        subject,
        _teacher,
        lessons,
        periods,
        mode,
        old_periods,
        old_mode,
    ) in changes:
        periods_changed = periods != old_periods
        mode_changed = mode != old_mode
        assignment.periods_per_week = periods
        assignment.block_mode = mode
        assignment.consecutive_pattern = ""

        if mode_changed or (periods_changed and assignment_requires_double(assignment)):
            fixed_error = normalize_assignment_fixed_rows(
                db, project, assignment, lessons
            )
            if fixed_error:
                raise HTTPException(
                    409,
                    f"Không thể đổi chương trình cho {school_class.name} – {subject.name}: {fixed_error}",
                )
            if not assignment_completion_feasible(
                db, project, assignment, [lesson.slot for lesson in lessons]
            ):
                raise HTTPException(
                    409,
                    f"Không thể đổi chương trình cho {school_class.name} – {subject.name} vì "
                    "các tiết hiện có không thể hoàn thành hợp lệ theo chế độ mới và các ràng buộc hiện tại.",
                )

    return len(changes)


def required_text(data: dict, key: str, label: str, max_length: int) -> str:
    return bounded_text(data.get(key, ""), label, max_length)


def required_id(data: dict, key: str, label: str) -> int:
    value = data.get(key)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"{label} không hợp lệ") from exc
    if parsed <= 0:
        raise HTTPException(400, f"{label} không hợp lệ")
    return parsed


@app.post("/api/projects/{pid}/entity")
def add_entity(
    pid: int,
    payload: EntityIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    d = payload.data
    teacher_subject_ids: list[int] | None = None
    if payload.type == "department":
        name = required_text(d, "name", "Tên tổ chuyên môn", 120)
        ensure_unique_project_name(db, Department, pid, name, "Tổ chuyên môn")
        obj = Department(project_id=pid, name=name)
    elif payload.type == "subject":
        name = required_text(d, "name", "Tên môn học", 120)
        ensure_unique_project_name(db, Subject, pid, name, "Môn học")
        max_consecutive = bounded_int(
            d.get("max_consecutive"),
            min(2, project.periods_per_session),
            1,
            project.periods_per_session,
            "Số tiết liên tiếp tối đa",
        )
        short_name = (str(d.get("short_name") or "").strip() or name[:5])[:20]
        obj = Subject(
            project_id=pid,
            name=name,
            short_name=short_name,
            max_consecutive=max_consecutive,
        )
    elif payload.type == "teacher":
        name = required_text(d, "name", "Tên giáo viên", 120)
        department_id = d.get("department_id") or None
        if department_id:
            try:
                department_id = int(department_id)
            except (TypeError, ValueError) as exc:
                raise HTTPException(400, "Tổ chuyên môn không hợp lệ") from exc
            department = db.get(Department, department_id)
            if not department or department.project_id != pid:
                raise HTTPException(400, "Tổ chuyên môn không hợp lệ")
        max_periods_day = bounded_int(
            d.get("max_periods_day"),
            min(5, project.sessions * project.periods_per_session),
            1,
            project.sessions * project.periods_per_session,
            "Số tiết tối đa mỗi ngày",
        )
        short_name = (str(d.get("short_name") or "").strip() or name)[:30]
        ensure_unique_teacher_short_name(db, pid, short_name)
        teacher_subject_ids = validated_subject_ids(db, pid, d.get("subject_ids", []))
        obj = Teacher(
            project_id=pid,
            name=name,
            short_name=short_name,
            department_id=department_id,
            max_periods_day=max_periods_day,
            unavailable_json=json.dumps(valid_slots(project, d.get("unavailable", []))),
        )
    elif payload.type == "grade":
        name = required_text(d, "name", "Tên khối lớp", 80)
        ensure_unique_project_name(db, Grade, pid, name, "Khối lớp")
        obj = Grade(project_id=pid, name=name)
    elif payload.type == "class":
        name = required_text(d, "name", "Tên lớp học", 80)
        ensure_unique_project_name(db, SchoolClass, pid, name, "Lớp học")
        grade_id = d.get("grade_id") or None
        if grade_id:
            try:
                grade_id = int(grade_id)
            except (TypeError, ValueError) as exc:
                raise HTTPException(400, "Khối lớp không hợp lệ") from exc
            grade = db.get(Grade, grade_id)
            if not grade or grade.project_id != pid:
                raise HTTPException(400, "Khối lớp không hợp lệ")
        obj = SchoolClass(
            project_id=pid,
            name=name,
            grade_id=grade_id,
            unavailable_json=json.dumps(valid_slots(project, d.get("unavailable", []))),
        )
    elif payload.type == "assignment":
        class_id = required_id(d, "class_id", "Lớp học")
        subject_id = required_id(d, "subject_id", "Môn học")
        teacher_id = required_id(d, "teacher_id", "Giáo viên")
        school_class = db.get(SchoolClass, class_id)
        subject = db.get(Subject, subject_id)
        teacher = db.get(Teacher, teacher_id)
        if (
            not school_class
            or not subject
            or not teacher
            or any(x.project_id != pid for x in (school_class, subject, teacher))
        ):
            raise HTTPException(
                400, "Lớp, môn hoặc giáo viên không thuộc bộ thời khóa biểu"
            )
        allowed = db.scalar(
            select(TeacherSubject.id).where(
                TeacherSubject.project_id == pid,
                TeacherSubject.teacher_id == teacher.id,
                TeacherSubject.subject_id == subject.id,
            )
        )
        if allowed is None:
            raise HTTPException(
                409, f"{teacher.name} chưa được cấu hình dạy môn {subject.name}"
            )
        duplicate = db.scalar(
            select(Assignment).where(
                Assignment.project_id == pid,
                Assignment.class_id == school_class.id,
                Assignment.subject_id == subject.id,
            )
        )
        if duplicate is not None:
            if duplicate.teacher_id == teacher.id:
                raise HTTPException(409, "Phân công lớp – môn này đã tồn tại")
            other = db.get(Teacher, duplicate.teacher_id)
            raise HTTPException(
                409,
                f"{school_class.name} – {subject.name} đã được phân công cho {other.name if other else 'giáo viên khác'}",
            )
        periods = bounded_int(d.get("periods_per_week"), 1, 1, 40, "Số tiết mỗi tuần")
        try:
            mode = normalized_block_mode(
                d.get("block_mode", "free"), periods, subject, project
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        ensure_assignment_matches_grade_requirement(
            db, project, school_class, subject, periods, mode
        )
        ensure_teacher_load_fits(
            db,
            project,
            teacher,
            teacher_assigned_periods(db, pid, teacher.id) + periods,
        )
        ensure_class_load_fits(
            project,
            school_class,
            class_assigned_periods(db, pid, school_class.id) + periods,
        )
        ensure_required_double_hard_feasible(
            project,
            teacher,
            school_class,
            subject,
            periods,
            mode,
        )
        obj = Assignment(
            project_id=pid,
            class_id=school_class.id,
            subject_id=subject.id,
            teacher_id=teacher.id,
            periods_per_week=periods,
            block_mode=mode,
            consecutive_pattern="",
        )
    else:
        raise HTTPException(400, "Loại dữ liệu không hợp lệ")
    db.add(obj)
    db.flush()
    if payload.type == "teacher" and teacher_subject_ids is not None:
        replace_teacher_subjects(db, pid, obj.id, teacher_subject_ids)
    if payload.type == "grade":
        replace_grade_requirements(
            db, project, obj.id, d.get("subject_requirements", [])
        )
    db.commit()
    return {"ok": True, "id": obj.id}


@app.post("/api/projects/{pid}/assignments/bulk")
def add_assignments_bulk(
    pid: int,
    payload: BulkAssignmentIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    teacher = db.get(Teacher, payload.teacher_id)
    if not teacher or teacher.project_id != pid:
        raise HTTPException(400, "Giáo viên không thuộc bộ thời khóa biểu")

    class_ids = list(
        dict.fromkeys(int(value) for value in payload.class_ids if int(value) > 0)
    )
    if not class_ids:
        raise HTTPException(400, "Hãy chọn ít nhất một lớp học")

    raw_subjects = payload.subjects or [
        BulkAssignmentSubjectIn(
            subject_id=subject_id,
            periods_per_week=payload.periods_per_week,
            block_mode=payload.block_mode,
        )
        for subject_id in payload.subject_ids
    ]
    configs: dict[int, BulkAssignmentSubjectIn] = {}
    for config in raw_subjects:
        if config.subject_id > 0:
            configs[config.subject_id] = config
    subject_ids = list(configs)
    if not subject_ids:
        raise HTTPException(400, "Hãy chọn ít nhất một môn học")

    subjects = db.scalars(
        select(Subject).where(
            Subject.project_id == pid,
            Subject.id.in_(subject_ids),
        )
    ).all()
    classes = db.scalars(
        select(SchoolClass).where(
            SchoolClass.project_id == pid,
            SchoolClass.id.in_(class_ids),
        )
    ).all()
    subject_map = {item.id: item for item in subjects}
    class_map = {item.id: item for item in classes}
    if set(subject_map) != set(subject_ids):
        raise HTTPException(400, "Có môn học không thuộc bộ thời khóa biểu")
    if set(class_map) != set(class_ids):
        raise HTTPException(400, "Có lớp học không thuộc bộ thời khóa biểu")

    allowed_subject_ids = set(
        db.scalars(
            select(TeacherSubject.subject_id).where(
                TeacherSubject.project_id == pid,
                TeacherSubject.teacher_id == teacher.id,
                TeacherSubject.subject_id.in_(subject_ids),
            )
        ).all()
    )
    not_allowed = [
        subject_map[sid].name for sid in subject_ids if sid not in allowed_subject_ids
    ]
    if not_allowed:
        raise HTTPException(
            409,
            f"{teacher.name} chưa được cấu hình dạy: {', '.join(not_allowed)}",
        )

    normalized: dict[int, tuple[int, str]] = {}
    for subject_id, config in configs.items():
        subject = subject_map[subject_id]
        periods = bounded_int(
            config.periods_per_week, 1, 1, 40, f"Số tiết/tuần của {subject.name}"
        )
        try:
            mode = normalized_block_mode(config.block_mode, periods, subject, project)
        except ValueError as exc:
            raise HTTPException(400, f"{subject.name}: {exc}") from exc
        normalized[subject_id] = (periods, mode)

    existing_rows = db.scalars(
        select(Assignment).where(
            Assignment.project_id == pid,
            Assignment.subject_id.in_(subject_ids),
            Assignment.class_id.in_(class_ids),
        )
    ).all()
    existing_by_pair = defaultdict(list)
    for item in existing_rows:
        existing_by_pair[(item.subject_id, item.class_id)].append(item)
    existing_pairs = set(existing_by_pair)

    conflicts = []
    for subject_id in subject_ids:
        for class_id in class_ids:
            rows = existing_by_pair.get((subject_id, class_id), [])
            other_rows = [row for row in rows if row.teacher_id != teacher.id]
            if other_rows:
                other = db.get(Teacher, other_rows[0].teacher_id)
                conflicts.append(
                    f"{class_map[class_id].name} – {subject_map[subject_id].name} "
                    f"({other.name if other else 'giáo viên khác'})"
                )
    if conflicts:
        preview = "; ".join(conflicts[:5])
        suffix = f"; và {len(conflicts) - 5} cặp khác" if len(conflicts) > 5 else ""
        raise HTTPException(
            409,
            f"Không thể tạo vì môn của lớp đã được phân công cho giáo viên khác: {preview}{suffix}.",
        )

    curriculum_conflicts = []
    existing_config_conflicts = []
    for class_id in class_ids:
        school_class = class_map[class_id]
        for subject_id in subject_ids:
            periods, mode = normalized[subject_id]
            rows = existing_by_pair.get((subject_id, class_id), [])
            same_teacher_rows = [row for row in rows if row.teacher_id == teacher.id]
            requirement = grade_requirement_for_assignment(
                db, pid, school_class, subject_id
            )

            if requirement is not None:
                required_periods = int(requirement.periods_per_week)
                required_mode = requirement.block_mode or "free"
                if same_teacher_rows:
                    stale_rows = [
                        row
                        for row in same_teacher_rows
                        if int(row.periods_per_week) != required_periods
                        or (row.block_mode or "free") != required_mode
                    ]
                    if stale_rows:
                        current = stale_rows[0]
                        curriculum_conflicts.append(
                            f"{school_class.name} – {subject_map[subject_id].name}: "
                            f"phân công hiện có {int(current.periods_per_week)} tiết/tuần · "
                            f"{block_mode_text(current.block_mode or 'free')}, "
                            f"chương trình yêu cầu {required_periods} tiết/tuần · "
                            f"{block_mode_text(required_mode)}"
                        )
                elif periods != required_periods or mode != required_mode:
                    curriculum_conflicts.append(
                        f"{school_class.name} – {subject_map[subject_id].name}: "
                        f"yêu cầu {required_periods} tiết/tuần · {block_mode_text(required_mode)}, "
                        f"đang nhập {periods} tiết/tuần · {block_mode_text(mode)}"
                    )

            if same_teacher_rows:
                mismatched_rows = [
                    row
                    for row in same_teacher_rows
                    if int(row.periods_per_week) != periods
                    or (row.block_mode or "free") != mode
                ]
                if mismatched_rows:
                    current = mismatched_rows[0]
                    existing_config_conflicts.append(
                        f"{school_class.name} – {subject_map[subject_id].name}: "
                        f"đang có {int(current.periods_per_week)} tiết/tuần · "
                        f"{block_mode_text(current.block_mode or 'free')}, "
                        f"đang chọn {periods} tiết/tuần · {block_mode_text(mode)}"
                    )

    if curriculum_conflicts:
        preview = "; ".join(curriculum_conflicts[:5])
        suffix = (
            f"; và {len(curriculum_conflicts) - 5} cặp khác"
            if len(curriculum_conflicts) > 5
            else ""
        )
        raise HTTPException(
            409,
            "Không thể tiếp tục vì có phân công chưa khớp chương trình chuẩn theo khối: "
            f"{preview}{suffix}. Hãy sửa phân công hiện có trước khi phân công hàng loạt.",
        )

    if existing_config_conflicts:
        preview = "; ".join(existing_config_conflicts[:5])
        suffix = (
            f"; và {len(existing_config_conflicts) - 5} cặp khác"
            if len(existing_config_conflicts) > 5
            else ""
        )
        raise HTTPException(
            409,
            "Có phân công đã tồn tại nhưng cấu hình khác lựa chọn hiện tại: "
            f"{preview}{suffix}. Hãy sửa phân công hiện có hoặc bỏ cặp đó khỏi lần phân công này.",
        )

    added_periods = 0
    added_periods_by_class = Counter()
    for subject_id in subject_ids:
        periods, _ = normalized[subject_id]
        for class_id in class_ids:
            if (subject_id, class_id) not in existing_pairs:
                added_periods += periods
                added_periods_by_class[class_id] += periods
    current_periods = teacher_assigned_periods(db, pid, teacher.id)
    ensure_teacher_load_fits(db, project, teacher, current_periods + added_periods)
    for class_id, class_added_periods in added_periods_by_class.items():
        ensure_class_load_fits(
            project,
            class_map[class_id],
            class_assigned_periods(db, pid, class_id) + class_added_periods,
        )

    created = 0
    skipped = 0
    for subject_id in subject_ids:
        periods, mode = normalized[subject_id]
        for class_id in class_ids:
            if (subject_id, class_id) in existing_pairs:
                skipped += 1
                continue
            ensure_required_double_hard_feasible(
                project,
                teacher,
                class_map[class_id],
                subject_map[subject_id],
                periods,
                mode,
            )
            db.add(
                Assignment(
                    project_id=pid,
                    class_id=class_id,
                    subject_id=subject_id,
                    teacher_id=teacher.id,
                    periods_per_week=periods,
                    block_mode=mode,
                    consecutive_pattern="",
                )
            )
            created += 1

    db.commit()
    if created and skipped:
        message = f"Đã tạo {created} phân công; bỏ qua {skipped} phân công đã tồn tại."
    elif created:
        message = f"Đã tạo {created} phân công."
    else:
        message = f"Không tạo mới: {skipped} phân công đã tồn tại."
    return {"ok": True, "created": created, "skipped": skipped, "message": message}


@app.put("/api/projects/{pid}/entity/{typ}/{eid}")
def update_entity(
    pid: int,
    typ: str,
    eid: int,
    payload: EntityIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    if payload.type != typ or typ not in {"subject", "teacher", "grade", "class"}:
        raise HTTPException(400, "Loại dữ liệu không hợp lệ")
    model = {
        "subject": Subject,
        "teacher": Teacher,
        "grade": Grade,
        "class": SchoolClass,
    }[typ]
    obj = db.get(model, eid)
    if not obj or obj.project_id != pid:
        raise HTTPException(404, "Không tìm thấy dữ liệu cần sửa")
    d = payload.data
    synced_assignments = 0
    name_limit = {"subject": 120, "teacher": 120, "grade": 80, "class": 80}[typ]
    name = bounded_text(d.get("name", ""), "Tên", name_limit)
    if typ == "subject":
        ensure_unique_project_name(db, Subject, pid, name, "Môn học", exclude_id=obj.id)
        short_name = bounded_text(d.get("short_name", ""), "Tên rút gọn", 20)
        new_max_consecutive = bounded_int(
            d.get("max_consecutive"),
            min(obj.max_consecutive, project.periods_per_session),
            1,
            project.periods_per_session,
            "Số tiết liên tiếp tối đa",
        )
        assignments = db.scalars(
            select(Assignment).where(
                Assignment.project_id == pid,
                Assignment.subject_id == obj.id,
            )
        ).all()
        incompatible_assignments = [
            assignment.id
            for assignment in assignments
            if getattr(assignment, "block_mode", "free")
            in {"preferred_double", "required_double"}
            and assignment.periods_per_week >= 2
            and new_max_consecutive < 2
        ]

        assignment_by_id = {assignment.id: assignment for assignment in assignments}
        periods_by_class_session = defaultdict(list)
        periods_per_day = project.sessions * project.periods_per_session
        if assignment_by_id:
            lessons = db.scalars(
                select(Lesson).where(
                    Lesson.project_id == pid,
                    Lesson.assignment_id.in_(list(assignment_by_id)),
                )
            ).all()
            for lesson in lessons:
                assignment = assignment_by_id.get(lesson.assignment_id)
                if not assignment:
                    continue
                day = lesson.slot // periods_per_day
                inside_day = lesson.slot % periods_per_day
                session = inside_day // project.periods_per_session
                period = inside_day % project.periods_per_session
                periods_by_class_session[(assignment.class_id, day, session)].append(
                    period
                )

        violating_class_sessions = 0
        for periods in periods_by_class_session.values():
            longest = run = 0
            previous = None
            for period in sorted(set(periods)):
                run = run + 1 if previous is not None and period == previous + 1 else 1
                longest = max(longest, run)
                previous = period
            if longest > new_max_consecutive:
                violating_class_sessions += 1

        if incompatible_assignments or violating_class_sessions:
            details = []
            if incompatible_assignments:
                details.append(
                    f"{len(incompatible_assignments)} phân công đang dùng chế độ tiết đôi"
                )
            if violating_class_sessions:
                details.append(
                    f"{violating_class_sessions} buổi của lớp đang có cụm môn học dài hơn"
                )
            raise HTTPException(
                409,
                f"Không thể giảm còn {new_max_consecutive} tiết liên tiếp vì "
                + " và ".join(details)
                + ". Hãy điều chỉnh phân công hoặc lịch hiện tại trước.",
            )
        obj.name = name
        obj.short_name = short_name
        obj.max_consecutive = new_max_consecutive
    elif typ == "teacher":
        short_name = bounded_text(d.get("short_name", ""), "Tên ngắn", 30)
        ensure_unique_teacher_short_name(db, pid, short_name, exclude_id=obj.id)
        if "department_id" in d:
            department_id = d.get("department_id") or None
            if department_id is not None:
                try:
                    department_id = int(department_id)
                except (TypeError, ValueError) as exc:
                    raise HTTPException(400, "Tổ chuyên môn không hợp lệ") from exc
                department = db.get(Department, department_id)
                if not department or department.project_id != pid:
                    raise HTTPException(400, "Tổ chuyên môn không hợp lệ")
        else:
            department_id = obj.department_id
        new_max_periods_day = bounded_int(
            d.get("max_periods_day"),
            min(obj.max_periods_day, project.sessions * project.periods_per_session),
            1,
            project.sessions * project.periods_per_session,
            "Số tiết tối đa mỗi ngày",
        )
        assignment_ids = set(
            db.scalars(
                select(Assignment.id).where(
                    Assignment.project_id == pid,
                    Assignment.teacher_id == obj.id,
                )
            ).all()
        )
        if assignment_ids:
            ppd = project.sessions * project.periods_per_session
            daily_counts = Counter(
                slot // ppd
                for slot in db.scalars(
                    select(Lesson.slot).where(
                        Lesson.project_id == pid,
                        Lesson.assignment_id.in_(assignment_ids),
                    )
                ).all()
            )
            highest_current = max(daily_counts.values(), default=0)
            if highest_current > new_max_periods_day:
                raise HTTPException(
                    409,
                    f"Không thể giảm còn {new_max_periods_day} tiết/ngày vì lịch hiện tại có ngày giáo viên đang dạy {highest_current} tiết. Hãy điều chỉnh lịch trước.",
                )
        assigned_total = teacher_assigned_periods(db, pid, obj.id)
        ensure_teacher_load_fits(
            db, project, obj, assigned_total, max_periods_day=new_max_periods_day
        )
        for assignment in db.scalars(
            select(Assignment).where(
                Assignment.project_id == pid,
                Assignment.teacher_id == obj.id,
            )
        ).all():
            if not assignment_requires_double(assignment):
                continue
            school_class = db.get(SchoolClass, assignment.class_id)
            subject = db.get(Subject, assignment.subject_id)
            if school_class and subject:
                ensure_required_double_hard_feasible(
                    project,
                    obj,
                    school_class,
                    subject,
                    assignment.periods_per_week,
                    assignment.block_mode,
                    max_periods_day=new_max_periods_day,
                )
        if "subject_ids" in d:
            teacher_subject_ids = validated_subject_ids(db, pid, d.get("subject_ids"))
            assigned_subject_ids = set(
                db.scalars(
                    select(Assignment.subject_id).where(
                        Assignment.project_id == pid,
                        Assignment.teacher_id == obj.id,
                    )
                ).all()
            )
            removed_in_use = assigned_subject_ids - set(teacher_subject_ids)
            if removed_in_use:
                names = db.scalars(
                    select(Subject.name).where(Subject.id.in_(removed_in_use))
                ).all()
                raise HTTPException(
                    409,
                    "Không thể bỏ môn đang có phân công: "
                    + ", ".join(names)
                    + ". Hãy xóa/chuyển phân công trước.",
                )
            replace_teacher_subjects(db, pid, obj.id, teacher_subject_ids)
        obj.name = name
        obj.short_name = short_name
        obj.department_id = department_id
        obj.max_periods_day = new_max_periods_day
    elif typ == "grade":
        ensure_unique_project_name(db, Grade, pid, name, "Khối lớp", exclude_id=obj.id)
        if "subject_requirements" in d:
            proposed_configs = normalized_grade_requirements(
                db, project, d.get("subject_requirements", [])
            )
            current_rows = db.scalars(
                select(GradeSubjectRequirement).where(
                    GradeSubjectRequirement.project_id == pid,
                    GradeSubjectRequirement.grade_id == obj.id,
                )
            ).all()
            current_configs = sorted(
                (row.subject_id, int(row.periods_per_week), row.block_mode or "free")
                for row in current_rows
            )
            if sorted(proposed_configs) != current_configs:
                issues = grade_requirement_missing_assignments(
                    db, project, obj.id, proposed_configs
                )
                if issues:
                    preview = "; ".join(issues[:5])
                    suffix = (
                        f"; và {len(issues) - 5} mục khác" if len(issues) > 5 else ""
                    )
                    raise HTTPException(
                        409,
                        "Không thể thay đổi chương trình khối vì còn môn chưa có phân công: "
                        f"{preview}{suffix}. Hãy tạo phân công và chọn giáo viên trước.",
                    )
                synced_assignments += sync_assignments_to_grade_requirements(
                    db, project, obj.id, proposed_configs
                )
            replace_grade_requirements(
                db, project, obj.id, d.get("subject_requirements", [])
            )
        obj.name = name
    else:
        ensure_unique_project_name(
            db, SchoolClass, pid, name, "Lớp học", exclude_id=obj.id
        )
        if "grade_id" in d:
            grade_id = d.get("grade_id") or None
            if grade_id is not None:
                try:
                    grade_id = int(grade_id)
                except (TypeError, ValueError) as exc:
                    raise HTTPException(400, "Khối lớp không hợp lệ") from exc
                grade = db.get(Grade, grade_id)
                if not grade or grade.project_id != pid:
                    raise HTTPException(400, "Khối lớp không hợp lệ")
        else:
            grade_id = obj.grade_id
        if grade_id != obj.grade_id and grade_id is not None:
            proposed_rows = db.scalars(
                select(GradeSubjectRequirement).where(
                    GradeSubjectRequirement.project_id == pid,
                    GradeSubjectRequirement.grade_id == grade_id,
                )
            ).all()
            proposed_configs = [
                (row.subject_id, int(row.periods_per_week), row.block_mode or "free")
                for row in proposed_rows
            ]
            issues = grade_requirement_missing_assignments(
                db,
                project,
                grade_id,
                proposed_configs,
                classes=[obj],
            )
            if issues:
                grade = db.get(Grade, grade_id)
                preview = "; ".join(issues[:5])
                suffix = f"; và {len(issues) - 5} mục khác" if len(issues) > 5 else ""
                raise HTTPException(
                    409,
                    f"Không thể chuyển {obj.name} sang {grade.name if grade else 'khối mới'} vì "
                    f"còn môn chưa có phân công: {preview}{suffix}. "
                    "Hãy tạo phân công và chọn giáo viên trước.",
                )
            synced_assignments += sync_assignments_to_grade_requirements(
                db,
                project,
                grade_id,
                proposed_configs,
                classes=[obj],
            )
        obj.name = name
        obj.grade_id = grade_id
    db.commit()
    return {"ok": True, "synced_assignments": synced_assignments}


class AssignmentUpdateIn(BaseModel):
    periods_per_week: int
    block_mode: str = "free"


def normalize_assignment_fixed_rows(
    db: Session,
    project: Project,
    assignment: Assignment,
    lessons: list[Lesson],
) -> str | None:
    """Chuẩn hóa các ghim khi số tiết hoặc chế độ cụm thay đổi.

    Lesson.locked là nguồn dữ liệu thật. Ở chế độ tự do/ưu tiên, mỗi tiết khóa
    có một FixedLesson riêng. Ở chế độ bắt buộc tiết đôi, các tiết khóa phải tự
    tạo thành những cụm hoàn chỉnh được chế độ mới cho phép; không tự ý khóa
    thêm một tiết lân cận vì điều đó sẽ thay đổi lựa chọn của người dùng.
    """
    locked_slots = sorted(lesson.slot for lesson in lessons if lesson.locked)
    replacement_rows = []
    if assignment_requires_double(assignment):
        expected = Counter(assignment_groups(assignment))
        used = Counter()
        for run in required_double_slot_groups(project, locked_slots):
            size = run["size"]
            if expected[size] <= used[size]:
                return (
                    "Các tiết cố định hiện tại không tạo thành các cặp/tiết lẻ "
                    "hợp lệ theo chế độ bắt buộc tiết đôi mới. Hãy bỏ cố định "
                    "hoặc sắp xếp lại các tiết cố định trước."
                )
            used[size] += 1
            replacement_rows.append((run["start"], size))
    else:
        replacement_rows = [(slot, 1) for slot in locked_slots]

    fixed_rows = db.scalars(
        select(FixedLesson).where(
            FixedLesson.project_id == project.id,
            FixedLesson.assignment_id == assignment.id,
        )
    ).all()
    for row in fixed_rows:
        db.delete(row)
    for slot, size in replacement_rows:
        db.add(
            FixedLesson(
                project_id=project.id,
                assignment_id=assignment.id,
                slot=slot,
                group_size=size,
            )
        )
    return None


@app.put("/api/projects/{pid}/assignments/{assignment_id}")
def update_assignment(
    pid: int,
    assignment_id: int,
    payload: AssignmentUpdateIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    assignment = db.get(Assignment, assignment_id)
    if not assignment or assignment.project_id != pid:
        raise HTTPException(404)
    periods = bounded_int(payload.periods_per_week, 1, 1, 40, "Số tiết mỗi tuần")
    lessons = db.scalars(
        select(Lesson).where(Lesson.assignment_id == assignment.id)
    ).all()
    scheduled = len(lessons)
    if periods < scheduled:
        return JSONResponse(
            {
                "ok": False,
                "message": f"Đang có {scheduled} tiết trên lịch. Hãy gỡ bớt tiết trước khi giảm số tiết/tuần.",
            },
            409,
        )
    subject = db.get(Subject, assignment.subject_id)
    if not subject or subject.project_id != pid:
        raise HTTPException(409, "Môn học của phân công không còn tồn tại")
    try:
        mode = normalized_block_mode(payload.block_mode, periods, subject, project)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    old_periods = assignment.periods_per_week
    old_mode = assignment.block_mode
    teacher = db.get(Teacher, assignment.teacher_id)
    if not teacher or teacher.project_id != pid:
        raise HTTPException(409, "Giáo viên của phân công không còn tồn tại")
    projected_total = (
        teacher_assigned_periods(db, pid, teacher.id) - old_periods + periods
    )
    ensure_teacher_load_fits(db, project, teacher, projected_total)
    school_class = db.get(SchoolClass, assignment.class_id)
    if not school_class or school_class.project_id != pid:
        raise HTTPException(409, "Lớp của phân công không còn tồn tại")
    ensure_assignment_matches_grade_requirement(
        db, project, school_class, subject, periods, mode
    )
    projected_class_total = (
        class_assigned_periods(db, pid, school_class.id) - old_periods + periods
    )
    ensure_class_load_fits(project, school_class, projected_class_total)
    ensure_required_double_hard_feasible(
        project,
        teacher,
        school_class,
        subject,
        periods,
        mode,
    )
    periods_changed = periods != old_periods
    mode_changed = mode != old_mode

    # Không xóa các Lesson đang có. Thay đổi được áp dụng trong transaction và
    # sẽ rollback nguyên vẹn nếu phần lịch hiện tại không tương thích.
    assignment.periods_per_week = periods
    assignment.block_mode = mode
    assignment.consecutive_pattern = ""

    if mode_changed or (periods_changed and assignment_requires_double(assignment)):
        fixed_error = normalize_assignment_fixed_rows(db, project, assignment, lessons)
        if fixed_error:
            db.rollback()
            return JSONResponse({"ok": False, "message": fixed_error}, 409)

    # Chỉ các thay đổi ảnh hưởng cấu trúc cụm mới cần chứng minh rằng những tiết
    # đã xếp vẫn có ít nhất một cách hoàn thành. Tăng số tiết ở chế độ tự do/
    # ưu tiên chỉ tạo phần còn thiếu trong khay và giữ nguyên toàn bộ lịch cũ.
    if (
        mode_changed or (periods_changed and assignment_requires_double(assignment))
    ) and not assignment_completion_feasible(
        db, project, assignment, [lesson.slot for lesson in lessons]
    ):
        db.rollback()
        return JSONResponse(
            {
                "ok": False,
                "message": "Không thể áp dụng thay đổi vì các tiết hiện có không thể hoàn thành hợp lệ theo chế độ mới và các ràng buộc hiện tại. Lịch cũ được giữ nguyên.",
            },
            409,
        )

    db.commit()
    return {"ok": True, "scheduled_preserved": scheduled}


ENTITY_MODELS = {
    "department": Department,
    "subject": Subject,
    "teacher": Teacher,
    "grade": Grade,
    "class": SchoolClass,
    "assignment": Assignment,
}


def entity_delete_dependency(db: Session, typ: str, eid: int):
    # Use explicit branches so deleting one entity does not execute dependency
    # queries for every other entity type.
    if typ == "department":
        return db.scalar(select(Teacher.id).where(Teacher.department_id == eid))
    if typ == "subject":
        dependency = db.scalar(
            select(Assignment.id).where(Assignment.subject_id == eid)
        )
        if dependency is not None:
            return dependency
        return db.scalar(
            select(GradeSubjectRequirement.id).where(
                GradeSubjectRequirement.subject_id == eid
            )
        )
    if typ == "teacher":
        return db.scalar(select(Assignment.id).where(Assignment.teacher_id == eid))
    if typ == "grade":
        return db.scalar(select(SchoolClass.id).where(SchoolClass.grade_id == eid))
    if typ == "class":
        return db.scalar(select(Assignment.id).where(Assignment.class_id == eid))
    return None


def entity_delete_dependency_ids(db: Session, typ: str, ids: list[int]) -> set[int]:
    """Return selected entity IDs that are still referenced, in batch."""
    wanted = {int(value) for value in ids}
    if not wanted or typ == "assignment":
        return set()
    if typ == "department":
        return set(
            db.scalars(
                select(Teacher.department_id).where(Teacher.department_id.in_(wanted))
            ).all()
        )
    if typ == "subject":
        assigned = set(
            db.scalars(
                select(Assignment.subject_id).where(Assignment.subject_id.in_(wanted))
            ).all()
        )
        required = set(
            db.scalars(
                select(GradeSubjectRequirement.subject_id).where(
                    GradeSubjectRequirement.subject_id.in_(wanted)
                )
            ).all()
        )
        return assigned | required
    if typ == "teacher":
        return set(
            db.scalars(
                select(Assignment.teacher_id).where(Assignment.teacher_id.in_(wanted))
            ).all()
        )
    if typ == "grade":
        return set(
            db.scalars(
                select(SchoolClass.grade_id).where(SchoolClass.grade_id.in_(wanted))
            ).all()
        )
    if typ == "class":
        return set(
            db.scalars(
                select(Assignment.class_id).where(Assignment.class_id.in_(wanted))
            ).all()
        )
    return set()


def delete_entity_related_rows(db: Session, typ: str, eid: int):
    if typ == "assignment":
        for l in db.scalars(select(Lesson).where(Lesson.assignment_id == eid)).all():
            db.delete(l)
        for fixed_lesson in db.scalars(
            select(FixedLesson).where(FixedLesson.assignment_id == eid)
        ).all():
            db.delete(fixed_lesson)
    if typ == "subject":
        for link in db.scalars(
            select(TeacherSubject).where(TeacherSubject.subject_id == eid)
        ).all():
            db.delete(link)
        for requirement in db.scalars(
            select(GradeSubjectRequirement).where(
                GradeSubjectRequirement.subject_id == eid
            )
        ).all():
            db.delete(requirement)
    if typ == "grade":
        for requirement in db.scalars(
            select(GradeSubjectRequirement).where(
                GradeSubjectRequirement.grade_id == eid
            )
        ).all():
            db.delete(requirement)
    if typ == "teacher":
        for link in db.scalars(
            select(TeacherSubject).where(TeacherSubject.teacher_id == eid)
        ).all():
            db.delete(link)
        for preference in db.scalars(
            select(TeacherPreference).where(TeacherPreference.teacher_id == eid)
        ).all():
            db.delete(preference)


@app.delete("/api/projects/{pid}/entity/{typ}/{eid}")
def delete_entity(
    pid: int,
    typ: str,
    eid: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    get_project_for_update(pid, user, db)
    model = ENTITY_MODELS.get(typ)
    if not model:
        raise HTTPException(400)
    obj = db.get(model, eid)
    if not obj or obj.project_id != pid:
        raise HTTPException(404)
    if entity_delete_dependency(db, typ, eid) is not None:
        return JSONResponse(
            {"ok": False, "message": "Không thể xóa vì dữ liệu đang được sử dụng."}, 409
        )
    delete_entity_related_rows(db, typ, eid)
    db.delete(obj)
    db.commit()
    return {"ok": True}


class BulkEntityDeleteIn(BaseModel):
    type: str
    ids: list[int]


@app.delete("/api/projects/{pid}/entities/bulk")
def delete_entities_bulk(
    pid: int,
    payload: BulkEntityDeleteIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    """Xóa nhiều dòng cùng loại, nhưng không bỏ qua kiểm tra phụ thuộc."""
    get_project_for_update(pid, user, db)
    typ = (payload.type or "").strip().lower()
    model = ENTITY_MODELS.get(typ)
    if not model:
        raise HTTPException(400, "Loại dữ liệu không hợp lệ")

    ids = []
    seen = set()
    for raw_id in payload.ids:
        try:
            eid = int(raw_id)
        except (TypeError, ValueError):
            continue
        if eid > 0 and eid not in seen:
            seen.add(eid)
            ids.append(eid)
    if not ids:
        raise HTTPException(400, "Chưa chọn dữ liệu để xóa")
    if len(ids) > 500:
        raise HTTPException(400, "Mỗi lần chỉ được xóa tối đa 500 mục")

    rows = db.scalars(
        select(model).where(model.project_id == pid, model.id.in_(ids))
    ).all()
    row_by_id = {row.id: row for row in rows}
    blocked_ids = entity_delete_dependency_ids(db, typ, list(row_by_id))
    deleted_ids = []
    skipped = []
    for eid in ids:
        obj = row_by_id.get(eid)
        if obj is None:
            skipped.append(
                {"id": eid, "reason": "Không còn tồn tại trong bộ thời khóa biểu này."}
            )
            continue
        if eid in blocked_ids:
            skipped.append(
                {
                    "id": eid,
                    "name": str(getattr(obj, "name", "") or ""),
                    "reason": "Dữ liệu đang được sử dụng.",
                }
            )
            continue
        delete_entity_related_rows(db, typ, eid)
        db.delete(obj)
        deleted_ids.append(eid)

    if not deleted_ids:
        db.rollback()
        return JSONResponse(
            {
                "ok": False,
                "deleted": 0,
                "skipped": skipped,
                "message": "Không có mục nào được xóa. Các mục đã chọn đang được sử dụng hoặc không còn tồn tại.",
            },
            409,
        )

    db.commit()
    message = f"Đã xóa {len(deleted_ids)} mục."
    if skipped:
        message += (
            f" Bỏ qua {len(skipped)} mục đang được sử dụng hoặc không còn tồn tại."
        )
    return {
        "ok": True,
        "deleted": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "skipped": skipped,
        "message": message,
    }


class ConstraintIn(BaseModel):
    entity_type: str
    entity_id: int
    slots: list[int]
    confirm_displacement: bool = False
    confirmed_affected_lessons: int | None = None


@app.post("/api/projects/{pid}/constraints")
def constraints(
    pid: int,
    payload: ConstraintIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    p = get_project_for_update(pid, user, db)
    if payload.entity_type not in {"teacher", "class"}:
        raise HTTPException(400, "Loại ràng buộc không hợp lệ")
    model = Teacher if payload.entity_type == "teacher" else SchoolClass
    obj = db.get(model, payload.entity_id)
    if not obj or obj.project_id != pid:
        raise HTTPException(404)
    slots = set(valid_slots(p, payload.slots))
    assignments = db.scalars(
        select(Assignment).where(
            Assignment.project_id == pid,
            Assignment.teacher_id == obj.id
            if payload.entity_type == "teacher"
            else Assignment.class_id == obj.id,
        )
    ).all()
    assignment_ids = {assignment.id for assignment in assignments}
    lessons = (
        db.scalars(
            select(Lesson).where(
                Lesson.project_id == pid,
                Lesson.assignment_id.in_(assignment_ids),
            )
        ).all()
        if assignment_ids
        else []
    )
    lessons_by_assignment = defaultdict(list)
    for lesson in lessons:
        lessons_by_assignment[lesson.assignment_id].append(lesson)

    for assignment in assignments:
        if not assignment_requires_double(assignment):
            continue
        teacher = db.get(Teacher, assignment.teacher_id)
        school_class = db.get(SchoolClass, assignment.class_id)
        subject = db.get(Subject, assignment.subject_id)
        if not teacher or not school_class or not subject:
            continue
        ensure_required_double_hard_feasible(
            p,
            teacher,
            school_class,
            subject,
            assignment.periods_per_week,
            assignment.block_mode,
            teacher_unavailable_slots=slots
            if payload.entity_type == "teacher"
            else None,
            class_unavailable_slots=slots if payload.entity_type == "class" else None,
        )

    fixed_rows = (
        db.scalars(
            select(FixedLesson).where(
                FixedLesson.project_id == pid,
                FixedLesson.assignment_id.in_(assignment_ids),
            )
        ).all()
        if assignment_ids
        else []
    )
    assignment_by_id = {assignment.id: assignment for assignment in assignments}
    for row in fixed_rows:
        assignment = assignment_by_id.get(row.assignment_id)
        if not assignment:
            continue
        size = fixed_row_size(
            p, assignment, row, lessons_by_assignment[row.assignment_id]
        )
        if size < 1:
            return JSONResponse(
                {
                    "ok": False,
                    "message": "Có dữ liệu tiết cố định cũ không xác định được kích thước cụm. Hãy bỏ ghim đó rồi lưu ràng buộc lại.",
                },
                409,
            )
        if slots.intersection(range(row.slot, row.slot + size)):
            return JSONResponse(
                {
                    "ok": False,
                    "message": "Ràng buộc mới xung đột với tiết cố định. Hãy bỏ cố định trước.",
                },
                409,
            )

    removed_ids = set()
    for assignment in assignments:
        assignment_lessons = lessons_by_assignment[assignment.id]
        if not assignment_requires_double(assignment):
            affected = [lesson for lesson in assignment_lessons if lesson.slot in slots]
            if any(lesson.locked for lesson in affected):
                return JSONResponse(
                    {
                        "ok": False,
                        "message": "Ràng buộc mới xung đột với tiết cố định. Hãy bỏ cố định trước.",
                    },
                    409,
                )
            removed_ids.update(lesson.id for lesson in affected)
            continue
        for run in required_double_slot_groups(
            p, [lesson.slot for lesson in assignment_lessons]
        ):
            if not slots.intersection(run["slots"]):
                continue
            run_slots = set(run["slots"])
            affected = [
                lesson for lesson in assignment_lessons if lesson.slot in run_slots
            ]
            if any(lesson.locked for lesson in affected):
                return JSONResponse(
                    {
                        "ok": False,
                        "message": "Ràng buộc mới xung đột với tiết cố định. Hãy bỏ cố định trước.",
                    },
                    409,
                )
            removed_ids.update(lesson.id for lesson in affected)

    if removed_ids and (
        not payload.confirm_displacement
        or payload.confirmed_affected_lessons != len(removed_ids)
    ):
        return JSONResponse(
            {
                "ok": False,
                "requires_confirmation": True,
                "affected_lessons": len(removed_ids),
                "message": (
                    f"Thay đổi này sẽ đưa {len(removed_ids)} tiết đang xếp về khay. "
                    "Bạn có muốn tiếp tục không?"
                ),
            },
            409,
        )

    if payload.entity_type == "teacher":
        ensure_teacher_load_fits(
            db,
            p,
            obj,
            teacher_assigned_periods(db, pid, obj.id),
            unavailable_slots=slots,
        )
    else:
        ensure_class_load_fits(
            p,
            obj,
            class_assigned_periods(db, pid, obj.id),
            unavailable_slots=slots,
        )
    obj.unavailable_json = json.dumps(sorted(slots))
    for lesson in lessons:
        if lesson.id in removed_ids:
            db.delete(lesson)
    db.commit()
    return {"ok": True, "removed": len(removed_ids)}


class SessionLocksIn(BaseModel):
    sessions: list[int] = Field(default_factory=list)
    slots: list[int] = Field(default_factory=list)
    confirm_displacement: bool = False
    confirmed_affected_lessons: int | None = None


@app.post("/api/projects/{pid}/session-locks")
def save_session_locks(
    pid: int,
    payload: SessionLocksIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    maximum = project.days * project.sessions
    try:
        session_keys = normalize_slot_values(payload.sessions, maximum, strict=True)
    except ValueError as exc:
        message = str(exc).replace("tiết", "buổi")
        raise HTTPException(400, message) from exc
    blocked = []
    ppd = project.sessions * project.periods_per_session
    for key in session_keys:
        day = key // project.sessions
        session = key % project.sessions
        start = day * ppd + session * project.periods_per_session
        blocked.extend(range(start, start + project.periods_per_session))
    blocked = valid_slots(project, [*blocked, *payload.slots])
    all_lessons = db.scalars(select(Lesson).where(Lesson.project_id == pid)).all()
    lessons_by_assignment = defaultdict(list)
    for lesson in all_lessons:
        lessons_by_assignment[lesson.assignment_id].append(lesson)
    fixed_rows = db.scalars(
        select(FixedLesson).where(FixedLesson.project_id == pid)
    ).all()
    blocked_set = set(blocked)
    removed_ids = set()

    # Khóa buổi phải tuân cùng quy tắc với ràng buộc giáo viên/lớp:
    # không âm thầm xóa các cụm đã được cố định.
    for row in fixed_rows:
        assignment = db.get(Assignment, row.assignment_id)
        if not assignment:
            continue
        lessons = lessons_by_assignment.get(row.assignment_id, [])
        size = fixed_row_size(project, assignment, row, lessons)
        if size < 1:
            return JSONResponse(
                {
                    "ok": False,
                    "message": "Có dữ liệu tiết cố định cũ không xác định được kích thước cụm. Hãy bỏ ghim đó trước khi đổi khóa buổi/tiết.",
                },
                409,
            )
        row_slots = set(range(row.slot, row.slot + size))
        if blocked_set.intersection(row_slots):
            return JSONResponse(
                {
                    "ok": False,
                    "message": "Buổi hoặc tiết mới khóa đang chứa tiết cố định. Hãy bỏ cố định trước.",
                },
                409,
            )
    if any(lesson.locked and lesson.slot in blocked_set for lesson in all_lessons):
        return JSONResponse(
            {
                "ok": False,
                "message": "Buổi hoặc tiết mới khóa đang chứa tiết cố định. Hãy bỏ cố định trước.",
            },
            409,
        )

    teachers = db.scalars(select(Teacher).where(Teacher.project_id == pid)).all()
    for teacher in teachers:
        assigned = teacher_assigned_periods(db, pid, teacher.id)
        if assigned:
            ensure_teacher_load_fits(
                db,
                project,
                teacher,
                assigned,
                project_blocked_slots=blocked_set,
            )
    classes = db.scalars(select(SchoolClass).where(SchoolClass.project_id == pid)).all()
    for school_class in classes:
        assigned = class_assigned_periods(db, pid, school_class.id)
        if assigned:
            ensure_class_load_fits(
                project,
                school_class,
                assigned,
                project_blocked_slots=blocked_set,
            )

    teacher_map = {teacher.id: teacher for teacher in teachers}
    class_map = {school_class.id: school_class for school_class in classes}
    for assignment in db.scalars(
        select(Assignment).where(Assignment.project_id == pid)
    ).all():
        if not assignment_requires_double(assignment):
            continue
        teacher = teacher_map.get(assignment.teacher_id)
        school_class = class_map.get(assignment.class_id)
        subject = db.get(Subject, assignment.subject_id)
        if teacher and school_class and subject:
            ensure_required_double_hard_feasible(
                project,
                teacher,
                school_class,
                subject,
                assignment.periods_per_week,
                assignment.block_mode,
                project_blocked_slots=blocked_set,
            )

    for assignment_id, lessons in lessons_by_assignment.items():
        if not any(lesson.slot in blocked_set for lesson in lessons):
            continue
        assignment = db.get(Assignment, assignment_id)
        if not assignment:
            for lesson in lessons:
                if lesson.slot in blocked_set:
                    removed_ids.add(lesson.id)
            continue
        if not assignment_requires_double(assignment):
            removed_ids.update(
                lesson.id for lesson in lessons if lesson.slot in blocked_set
            )
            continue
        for run in required_double_slot_groups(project, [lesson.slot for lesson in lessons]):
            if blocked_set.intersection(run["slots"]):
                run_slots = set(run["slots"])
                removed_ids.update(
                    lesson.id for lesson in lessons if lesson.slot in run_slots
                )
    if removed_ids and (
        not payload.confirm_displacement
        or payload.confirmed_affected_lessons != len(removed_ids)
    ):
        return JSONResponse(
            {
                "ok": False,
                "requires_confirmation": True,
                "affected_lessons": len(removed_ids),
                "message": (
                    f"Thay đổi này sẽ đưa {len(removed_ids)} tiết đang xếp về khay. "
                    "Bạn có muốn tiếp tục không?"
                ),
            },
            409,
        )

    project.blocked_slots_json = json.dumps(blocked)
    for lesson in all_lessons:
        if lesson.id in removed_ids:
            db.delete(lesson)
    db.commit()
    return {"ok": True, "sessions": session_keys, "removed": len(removed_ids)}


class FixedIn(BaseModel):
    assignment_id: int
    slot: int


def fixed_row_size(
    project: Project,
    assignment: Assignment,
    row: FixedLesson,
    lessons: list[Lesson] | None = None,
) -> int:
    if not assignment_requires_double(assignment):
        return 1
    expected = assignment_groups(assignment)
    size = int(getattr(row, "group_size", 1) or 1)

    # group_size > 1 được ghi rõ khi người dùng cố định một cặp. Đây phải là
    # nguồn dữ liệu ưu tiên để một cặp 2 tiết không bị hạ thành 1 chỉ vì Lesson
    # đang tạm thiếu một tiết. Giá trị 1 vẫn được phép suy luận từ Lesson để
    # tương thích các FixedLesson legacy từng được migration với DEFAULT 1.
    if size > 1 and size in expected:
        return size

    if lessons:
        for run in required_double_slot_groups(project, [lesson.slot for lesson in lessons]):
            if (
                run["start"] == row.slot
                and row.slot in run["slots"]
                and run["size"] in expected
            ):
                return run["size"]

    if size in expected and not (size == 1 and 1 not in expected):
        return size

    # Dữ liệu legacy có DEFAULT 1 nhưng assignment chỉ cho phép cụm 2 không
    # được tự suy diễn thành 2 tiết. Trả 0 như sentinel "invalid" để các
    # luồng validate báo lỗi rõ ràng hoặc cho người dùng gỡ ghim cũ.
    return 0


def fixed_coverage_slots(db: Session, project: Project):
    """Trả về các ô phải khóa theo mọi FixedLesson của project."""
    assignments = {
        assignment.id: assignment
        for assignment in db.scalars(
            select(Assignment).where(Assignment.project_id == project.id)
        ).all()
    }
    lessons_by_assignment = defaultdict(list)
    for lesson in db.scalars(
        select(Lesson).where(Lesson.project_id == project.id)
    ).all():
        lessons_by_assignment[lesson.assignment_id].append(lesson)

    coverage = defaultdict(set)
    for row in db.scalars(
        select(FixedLesson).where(FixedLesson.project_id == project.id)
    ).all():
        assignment = assignments.get(row.assignment_id)
        if not assignment:
            continue
        size = fixed_row_size(
            project,
            assignment,
            row,
            lessons_by_assignment[assignment.id],
        )
        if size < 1:
            continue
        coverage[assignment.id].update(range(row.slot, row.slot + size))
    return coverage


def add_generated_lessons(
    db: Session,
    project: Project,
    rows: list[tuple[int, int, bool]],
):
    """Ghi kết quả solver và bảo toàn bất biến FixedLesson => locked."""
    fixed_slots = fixed_coverage_slots(db, project)
    for assignment_id, slot, locked in rows:
        db.add(
            Lesson(
                project_id=project.id,
                assignment_id=assignment_id,
                slot=slot,
                locked=bool(locked or slot in fixed_slots[assignment_id]),
            )
        )


@app.post("/api/projects/{pid}/fixed")
def fixed(
    pid: int,
    payload: FixedIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    p = get_project_for_update(pid, user, db)
    assignment = db.get(Assignment, payload.assignment_id)
    if not assignment or assignment.project_id != pid:
        raise HTTPException(404)
    if payload.slot not in set(all_slots(p)):
        raise HTTPException(400, "Ô thời khóa biểu không hợp lệ")
    lessons = db.scalars(
        select(Lesson).where(
            Lesson.project_id == pid, Lesson.assignment_id == assignment.id
        )
    ).all()
    if assignment_requires_double(assignment):
        run = next(
            (
                item
                for item in required_double_slot_groups(
                    p, [lesson.slot for lesson in lessons]
                )
                if payload.slot in item["slots"]
            ),
            None,
        )
    else:
        selected = next(
            (lesson for lesson in lessons if lesson.slot == payload.slot), None
        )
        run = (
            {"start": payload.slot, "size": 1, "slots": [payload.slot]}
            if selected
            else None
        )
    if not run:
        # Tương thích với client cũ: payload.slot từng được hiểu là ô đích.
        # Chỉ cho phép khi phân công chưa có cụm cố định để tránh làm mất các ghim khác.
        existing_fixed = db.scalars(
            select(FixedLesson).where(
                FixedLesson.project_id == pid,
                FixedLesson.assignment_id == assignment.id,
            )
        ).all()
        if existing_fixed:
            raise HTTPException(
                409,
                "Hãy chọn trực tiếp một tiết đang có trên lịch để cố định tiết hoặc cặp đó",
            )
        groups = assignment_groups(assignment)
        size = groups[0] if groups else 1
        day, session, period = slot_meta(p, payload.slot)
        if period + size > p.periods_per_session:
            raise HTTPException(409, "Cặp tiết cố định vượt quá cuối buổi học")
        for lesson in lessons:
            if lesson.locked:
                raise HTTPException(
                    409,
                    "Phân công đang có tiết cố định; không thể dùng chế độ di chuyển cũ",
                )
            db.delete(lesson)
        db.add(
            FixedLesson(
                project_id=pid,
                assignment_id=assignment.id,
                slot=payload.slot,
                group_size=size,
            )
        )
        db.flush()
        result = solve_missing(db, p, tries=180, target_assignment_ids={assignment.id})
        target = [row for row in result["lessons"] if row[0] == assignment.id]
        if len(target) < assignment.periods_per_week:
            db.rollback()
            return JSONResponse(
                {
                    "ok": False,
                    "message": "Không thể cố định phân công tại vị trí này vì xung đột lớp, giáo viên hoặc ràng buộc.",
                },
                409,
            )
        add_generated_lessons(db, p, result["lessons"])
        db.commit()
        return {
            "ok": True,
            "message": f"Đã chuyển và cố định {size} tiết tại ô đã chọn.",
        }
    if (
        remaining_pattern_groups(p, assignment, [lesson.slot for lesson in lessons])
        is None
    ):
        raise HTTPException(
            409,
            "Lịch hiện tại chưa phù hợp với chế độ xếp tiết; hãy xếp lại trước khi cố định",
        )
    expected = Counter(assignment_groups(assignment))
    if expected[run["size"]] <= 0:
        raise HTTPException(
            409, "Tiết hoặc cặp đang chọn không phù hợp với chế độ của phân công"
        )
    # Cố định chỉ được phép khi chính lịch hiện tại đang hợp lệ. Không bỏ qua
    # các tiết chưa cố định: nếu chúng đang trùng lớp/giáo viên hoặc làm vượt
    # ràng buộc ngày/liên tiếp thì người dùng phải xử lý/xếp lại trước khi ghim.
    # Nhờ vậy thao tác ghim không để lại một trạng thái lịch xung đột.
    for lesson in lessons:
        if lesson.slot not in run["slots"]:
            continue
        error = lesson_slot_error(
            db,
            p,
            assignment,
            lesson.slot,
            lesson.id,
        )
        if error:
            raise HTTPException(409, error)

    fixed_rows = db.scalars(
        select(FixedLesson).where(
            FixedLesson.project_id == pid, FixedLesson.assignment_id == assignment.id
        )
    ).all()
    used = Counter()
    for row in fixed_rows:
        size = fixed_row_size(p, assignment, row, lessons)
        if size < 1:
            raise HTTPException(
                409,
                "Có dữ liệu tiết cố định cũ không xác định được kích thước cụm. Hãy bỏ ghim cũ trước khi cố định thêm.",
            )
        if row.slot == run["start"]:
            row.group_size = run["size"]
            for lesson in lessons:
                if lesson.slot in run["slots"]:
                    lesson.locked = True
            db.commit()
            return {"ok": True, "message": f"Đã cố định {run['size']} tiết đang chọn."}
        used[size] += 1
    if used[run["size"]] >= expected[run["size"]]:
        raise HTTPException(
            409, "Số tiết/cặp cố định đã vượt số lượng cho phép của phân công"
        )
    for lesson in lessons:
        if lesson.slot in run["slots"]:
            lesson.locked = True
    db.add(
        FixedLesson(
            project_id=pid,
            assignment_id=assignment.id,
            slot=run["start"],
            group_size=run["size"],
        )
    )
    db.commit()
    return {"ok": True, "message": f"Đã cố định {run['size']} tiết đang chọn."}


@app.delete("/api/projects/{pid}/fixed/{assignment_id}/{slot}")
def remove_fixed_group(
    pid: int,
    assignment_id: int,
    slot: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    p = get_project_for_update(pid, user, db)
    assignment = db.get(Assignment, assignment_id)
    if not assignment or assignment.project_id != pid:
        raise HTTPException(404)
    lessons = db.scalars(
        select(Lesson).where(
            Lesson.project_id == pid, Lesson.assignment_id == assignment_id
        )
    ).all()
    rows = db.scalars(
        select(FixedLesson).where(
            FixedLesson.project_id == pid, FixedLesson.assignment_id == assignment_id
        )
    ).all()
    targets = []
    for row in rows:
        size = fixed_row_size(p, assignment, row, lessons)
        if size < 1:
            # Cho phép người dùng gỡ chính ghim legacy lỗi tại ô gốc, nhưng
            # tuyệt đối không suy diễn nó thành một cặp 2 tiết.
            if row.slot == slot:
                targets.append((row, 1))
            continue
        if row.slot <= slot < row.slot + size:
            targets.append((row, size))
    if not targets:
        raise HTTPException(404, "Không tìm thấy tiết hoặc cặp cố định")
    unlocked = set()
    for row, size in targets:
        unlocked.update(range(row.slot, row.slot + size))
        db.delete(row)
    remaining = []
    for row in rows:
        if all(row.id != target.id for target, _size in targets):
            size = fixed_row_size(p, assignment, row, lessons)
            if size < 1:
                continue
            remaining.extend(range(row.slot, row.slot + size))
    for lesson in lessons:
        if lesson.slot in unlocked and lesson.slot not in remaining:
            lesson.locked = False
    db.commit()
    return {"ok": True, "message": "Đã bỏ cố định tiết hoặc cặp đang chọn."}


@app.delete("/api/projects/{pid}/fixed/{assignment_id}")
def remove_fixed(
    pid: int,
    assignment_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    get_project_for_update(pid, user, db)
    assignment = db.get(Assignment, assignment_id)
    if not assignment or assignment.project_id != pid:
        raise HTTPException(404)
    fixed_rows = db.scalars(
        select(FixedLesson).where(
            FixedLesson.project_id == pid, FixedLesson.assignment_id == assignment_id
        )
    ).all()
    for row in fixed_rows:
        db.delete(row)
    lessons = db.scalars(
        select(Lesson).where(
            Lesson.project_id == pid, Lesson.assignment_id == assignment_id
        )
    ).all()
    for lesson in lessons:
        lesson.locked = False
    db.commit()
    return {"ok": True, "message": "Đã bỏ toàn bộ cố định của phân công."}


class GenerateScheduleIn(BaseModel):
    allow_rebuild: bool = False


def minimal_schedule_invalid_lessons(
    db: Session,
    project: Project,
    assignments: list[Assignment],
    lessons: list[Lesson],
) -> list[Lesson]:
    """Giữ tối đa các tiết cũ hợp lệ và chỉ loại phần thực sự gây xung đột.

    Cách kiểm tra cũ gọi ``lesson_slot_error`` độc lập cho từng tiết. Với ràng
    buộc tổng hợp (ví dụ giáo viên tối đa 4 tiết/ngày nhưng đang có 5 tiết),
    mỗi tiết đều nhìn thấy 4 tiết còn lại và cả 5 cùng bị đánh dấu sai.

    Hàm này dựng lại trạng thái hợp lệ theo thứ tự ưu tiên:
    1. tiết cố định trước;
    2. tiết di động theo vị trí hiện tại.

    Một tiết chỉ bị loại khi thêm chính nó làm phát sinh vi phạm. Nhờ vậy giới
    hạn tiết/ngày, số tiết liên tiếp và xung đột cùng ô chỉ gỡ số tiết tối thiểu
    cần thiết, đồng thời không hy sinh tiết cố định để giữ một tiết di động.
    """
    assignment_by_id = {assignment.id: assignment for assignment in assignments}
    teachers = {
        teacher.id: teacher
        for teacher in db.scalars(
            select(Teacher).where(Teacher.project_id == project.id)
        ).all()
    }
    classes = {
        school_class.id: school_class
        for school_class in db.scalars(
            select(SchoolClass).where(SchoolClass.project_id == project.id)
        ).all()
    }
    subjects = {
        subject.id: subject
        for subject in db.scalars(
            select(Subject).where(Subject.project_id == project.id)
        ).all()
    }
    teacher_unavailable = {
        teacher_id: parse_slots(teacher.unavailable_json)
        for teacher_id, teacher in teachers.items()
    }
    class_unavailable = {
        class_id: parse_slots(school_class.unavailable_json)
        for class_id, school_class in classes.items()
    }

    maximum = project.days * project.sessions * project.periods_per_session
    periods_per_day = project.sessions * project.periods_per_session
    blocked = parse_slots(project.blocked_slots_json)

    teacher_slot_busy: set[tuple[int, int]] = set()
    class_slot_busy: set[tuple[int, int]] = set()
    teacher_day_counts: Counter[tuple[int, int]] = Counter()
    class_subject_session_periods: dict[tuple[int, int, int, int], set[int]] = (
        defaultdict(set)
    )
    invalid: list[Lesson] = []

    def exceeds_subject_run(periods: set[int], candidate: int, limit: int) -> bool:
        ordered = sorted(periods | {candidate})
        longest = current = 0
        previous = None
        for period in ordered:
            current = (
                current + 1 if previous is not None and period == previous + 1 else 1
            )
            longest = max(longest, current)
            previous = period
        return longest > limit

    # Tiết khóa luôn được xét trước. Trong cùng mức ưu tiên, giữ các vị trí sớm
    # hơn để kết quả ổn định giữa các lần chạy và để chuỗi liên tiếp được cắt ở
    # đúng phần dư thay vì đánh dấu cả chuỗi.
    ordered_lessons = sorted(
        lessons,
        key=lambda lesson: (
            0 if bool(lesson.locked) else 1,
            int(lesson.slot),
            int(lesson.id or 0),
        ),
    )

    for lesson in ordered_lessons:
        assignment = assignment_by_id.get(lesson.assignment_id)
        if not assignment:
            invalid.append(lesson)
            continue

        teacher = teachers.get(assignment.teacher_id)
        school_class = classes.get(assignment.class_id)
        subject = subjects.get(assignment.subject_id)
        if not teacher or not school_class or not subject:
            invalid.append(lesson)
            continue

        slot = int(lesson.slot)
        if slot < 0 or slot >= maximum:
            invalid.append(lesson)
            continue
        if (
            slot in blocked
            or slot in teacher_unavailable[teacher.id]
            or slot in class_unavailable[school_class.id]
        ):
            invalid.append(lesson)
            continue

        day = slot // periods_per_day
        inside_day = slot % periods_per_day
        session = inside_day // project.periods_per_session
        period = inside_day % project.periods_per_session
        teacher_slot_key = (assignment.teacher_id, slot)
        class_slot_key = (assignment.class_id, slot)
        teacher_day_key = (assignment.teacher_id, day)
        subject_run_key = (assignment.class_id, assignment.subject_id, day, session)

        if teacher_slot_key in teacher_slot_busy or class_slot_key in class_slot_busy:
            invalid.append(lesson)
            continue
        if teacher_day_counts[teacher_day_key] >= int(teacher.max_periods_day or 0):
            invalid.append(lesson)
            continue
        if exceeds_subject_run(
            class_subject_session_periods[subject_run_key],
            period,
            int(subject.max_consecutive or 0),
        ):
            invalid.append(lesson)
            continue

        teacher_slot_busy.add(teacher_slot_key)
        class_slot_busy.add(class_slot_key)
        teacher_day_counts[teacher_day_key] += 1
        class_subject_session_periods[subject_run_key].add(period)

    return invalid


@app.post("/api/projects/{pid}/generate")
def generate(
    pid: int,
    payload: Optional[GenerateScheduleIn] = None,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    p = get_project_for_update(pid, user, db)
    assignments = db.scalars(
        select(Assignment).where(Assignment.project_id == pid)
    ).all()
    reference_issues = assignment_project_reference_issues(db, pid, assignments)
    if reference_issues:
        labels = {"teacher_id": "giáo viên", "class_id": "lớp", "subject_id": "môn"}
        details = []
        for issue in reference_issues[:5]:
            refs = ", ".join(
                f"{labels.get(ref['field'], ref['field'])} #{ref['id']}"
                for ref in issue["invalid_refs"]
            )
            details.append(f"phân công #{issue['assignment_id']}: {refs}")
        suffix = (
            f"; và {len(reference_issues) - 5} phân công khác"
            if len(reference_issues) > 5
            else ""
        )
        return JSONResponse(
            {
                "ok": False,
                "reason": "assignment_project_mismatch",
                "assignment_reference_issues": reference_issues,
                "message": (
                    "Không thể xếp lịch vì có phân công tham chiếu giáo viên, lớp hoặc môn "
                    "không còn tồn tại hoặc thuộc project khác: "
                    + "; ".join(details)
                    + suffix
                    + ". Hãy sửa/xóa phân công lỗi trước khi xếp lại."
                ),
            },
            409,
        )
    duplicate_issues = duplicate_assignment_issues(db, assignments)
    if duplicate_issues:
        details = "; ".join(
            f"{item['class_name']} – {item['subject_name']} "
            f"(phân công ID {', '.join(map(str, item['assignment_ids']))})"
            for item in duplicate_issues[:5]
        )
        suffix = (
            f"; và {len(duplicate_issues) - 5} cặp khác"
            if len(duplicate_issues) > 5
            else ""
        )
        return JSONResponse(
            {
                "ok": False,
                "reason": "duplicate_assignments",
                "duplicate_assignment_issues": duplicate_issues,
                "message": (
                    "Không thể xếp lịch vì một lớp–môn đang có nhiều phân công: "
                    f"{details}{suffix}. Hãy xóa hoặc chuyển dữ liệu để mỗi lớp–môn "
                    "chỉ còn một giáo viên rồi xếp lại."
                ),
            },
            409,
        )
    classes = db.scalars(select(SchoolClass).where(SchoolClass.project_id == pid)).all()
    curriculum_issues = grade_requirement_assignment_issues(db, p, assignments, classes)
    if curriculum_issues:
        details = []
        for item in curriculum_issues[:5]:
            if item["issue_type"] == "missing":
                details.append(
                    f"{item['class_name']} – {item['subject_name']}: thiếu phân công "
                    f"{item['required_periods']} tiết/tuần"
                )
            else:
                mode_labels = {
                    "free": "Tự do",
                    "preferred_double": "Ưu tiên tiết đôi",
                    "required_double": "Bắt buộc tiết đôi",
                }
                current_mode = mode_labels.get(
                    item["assigned_mode"], item["assigned_mode"]
                )
                required_mode = mode_labels.get(
                    item["required_mode"], item["required_mode"]
                )
                details.append(
                    f"{item['class_name']} – {item['subject_name']}: đang {item['assigned_periods']} tiết/tuần · {current_mode}, "
                    f"chương trình khối yêu cầu {item['required_periods']} tiết/tuần · {required_mode}"
                )
        suffix = (
            f"; và {len(curriculum_issues) - 5} mục khác"
            if len(curriculum_issues) > 5
            else ""
        )
        return JSONResponse(
            {
                "ok": False,
                "reason": "grade_requirements_mismatch",
                "grade_requirement_issues": curriculum_issues,
                "message": (
                    "Không thể xếp lịch vì phân công chưa khớp chương trình chuẩn theo khối: "
                    + "; ".join(details)
                    + suffix
                    + ". Hãy bổ sung hoặc chỉnh phân công trước khi xếp tự động."
                ),
            },
            409,
        )
    capacity_issues = schedule_teacher_capacity_issues(db, p, assignments)
    if capacity_issues:
        details = "; ".join(
            f"{item['teacher_name']}: đã phân công {item['assigned']} tiết, "
            f"tối đa xếp được {item['capacity']} tiết (dư {item['excess']})"
            for item in capacity_issues[:5]
        )
        suffix = (
            f"; và {len(capacity_issues) - 5} giáo viên khác"
            if len(capacity_issues) > 5
            else ""
        )
        return JSONResponse(
            {
                "ok": False,
                "reason": "teacher_over_capacity",
                "capacity_issues": capacity_issues,
                "message": (
                    "Không thể xếp đầy đủ vì tải dạy vượt số ô khả dụng: "
                    f"{details}{suffix}. Hãy giảm/chuyển phân công, tăng giới hạn "
                    "tiết/ngày hoặc bỏ bớt tiết tránh rồi xếp lại."
                ),
            },
            409,
        )
    class_capacity_issues = schedule_class_capacity_issues(p, classes, assignments)
    if class_capacity_issues:
        details = "; ".join(
            f"{item['class_name']}: cần {item['assigned']} tiết, "
            f"chỉ còn {item['capacity']} ô (dư {item['excess']})"
            for item in class_capacity_issues[:5]
        )
        suffix = (
            f"; và {len(class_capacity_issues) - 5} lớp khác"
            if len(class_capacity_issues) > 5
            else ""
        )
        return JSONResponse(
            {
                "ok": False,
                "reason": "class_over_capacity",
                "class_capacity_issues": class_capacity_issues,
                "message": (
                    "Không thể xếp đầy đủ vì tải học của lớp vượt số ô khả dụng: "
                    f"{details}{suffix}. Hãy giảm phân công hoặc bỏ bớt khóa/tiết tránh của lớp."
                ),
            },
            409,
        )
    existing = db.scalars(select(Lesson).where(Lesson.project_id == pid)).all()
    assignment_by_id = {assignment.id: assignment for assignment in assignments}

    # Chuẩn hóa dữ liệu cố định cũ và hỗ trợ nhiều cụm cố định trên một phân công.
    lessons_by_assignment = defaultdict(list)
    for lesson in existing:
        lessons_by_assignment[lesson.assignment_id].append(lesson)
    fixed_rows = db.scalars(
        select(FixedLesson).where(FixedLesson.project_id == pid)
    ).all()
    fixed_changed = False
    assignments_with_unsatisfied_fixed = set()
    fixed_specs_by_assignment = defaultdict(list)
    for fixed_row in fixed_rows:
        assignment = assignment_by_id.get(fixed_row.assignment_id)
        if not assignment:
            db.delete(fixed_row)
            fixed_changed = True
            continue
        size = fixed_row_size(
            p, assignment, fixed_row, lessons_by_assignment[assignment.id]
        )
        if size < 1:
            return JSONResponse(
                {
                    "ok": False,
                    "message": (
                        "Có dữ liệu tiết cố định cũ không xác định được là tiết lẻ hay cặp tiết. "
                        "Hãy bỏ ghim tại ô đó rồi cố định lại trước khi xếp lịch."
                    ),
                },
                409,
            )
        fixed_specs_by_assignment[assignment.id].append((fixed_row.slot, size))
        if fixed_row.group_size != size:
            fixed_row.group_size = size
            fixed_changed = True
        expected_slots = set(range(fixed_row.slot, fixed_row.slot + size))
        matching = {
            lesson.slot: lesson
            for lesson in lessons_by_assignment[assignment.id]
            if lesson.slot in expected_slots
        }
        if expected_slots.issubset(matching):
            for slot in expected_slots:
                if not matching[slot].locked:
                    matching[slot].locked = True
                    fixed_changed = True
        else:
            assignments_with_unsatisfied_fixed.add(assignment.id)

    for assignment_id, fixed_specs in fixed_specs_by_assignment.items():
        assignment = assignment_by_id[assignment_id]
        fixed_error = fixed_group_validation_error(
            assignment_groups(assignment),
            fixed_specs,
            days=p.days,
            sessions=p.sessions,
            periods_per_session=p.periods_per_session,
        )
        if fixed_error:
            return JSONResponse(
                {
                    "ok": False,
                    "message": f"Dữ liệu tiết cố định của phân công không hợp lệ: {fixed_error} Hãy bỏ các ghim dư/trùng rồi xếp lại.",
                },
                409,
            )

    for assignment_id in assignments_with_unsatisfied_fixed:
        for lesson in lessons_by_assignment[assignment_id]:
            if not lesson.locked:
                db.delete(lesson)
                fixed_changed = True
    if fixed_changed:
        db.flush()
        existing = db.scalars(select(Lesson).where(Lesson.project_id == pid)).all()

    # Rà lại lịch cũ trước mỗi lần xếp vì các ràng buộc chính thức có thể đã
    # thay đổi sau khi lịch được tạo. Nguyện vọng giáo viên chỉ để tham khảo
    # và tuyệt đối không được đọc ở đây hoặc ở solver.
    invalid_lessons = []
    rebuild_assignment_ids = set()
    for lesson in minimal_schedule_invalid_lessons(db, p, assignments, existing):
        assignment = assignment_by_id.get(lesson.assignment_id)
        if not assignment:
            invalid_lessons.append(lesson)
            continue
        if lesson.locked:
            invalid_lessons.append(lesson)
        elif assignment_requires_double(assignment):
            rebuild_assignment_ids.add(assignment.id)
        else:
            invalid_lessons.append(lesson)

    existing_by_assignment = defaultdict(list)
    for lesson in existing:
        existing_by_assignment[lesson.assignment_id].append(lesson)
    for assignment in assignments:
        lessons_for_assignment = existing_by_assignment[assignment.id]
        if not lessons_for_assignment:
            continue
        slots_for_assignment = [lesson.slot for lesson in lessons_for_assignment]
        remaining_groups = remaining_pattern_groups(p, assignment, slots_for_assignment)
        if remaining_groups is None:
            rebuild_assignment_ids.add(assignment.id)

    if rebuild_assignment_ids:
        # Với required_double, lỗi ở một tiết di động chỉ yêu cầu dựng lại phần
        # di động của phân công. Các tiết khóa hợp lệ phải được giữ lại; chỉ khi
        # chính tập tiết khóa không thể thuộc bất kỳ mẫu hợp lệ nào mới báo lỗi
        # cố định.
        for assignment_id in rebuild_assignment_ids:
            assignment = assignment_by_id.get(assignment_id)
            assignment_lessons = [
                lesson for lesson in existing if lesson.assignment_id == assignment_id
            ]
            locked_assignment_lessons = [
                lesson for lesson in assignment_lessons if lesson.locked
            ]
            if assignment and locked_assignment_lessons:
                locked_slots = [lesson.slot for lesson in locked_assignment_lessons]
                if remaining_pattern_groups(p, assignment, locked_slots) is None:
                    invalid_lessons.extend(locked_assignment_lessons)
            invalid_lessons.extend(
                lesson for lesson in assignment_lessons if not lesson.locked
            )
    invalid_lessons = list({lesson.id: lesson for lesson in invalid_lessons}.values())
    locked_invalid = [lesson for lesson in invalid_lessons if lesson.locked]
    if locked_invalid:
        return JSONResponse(
            {
                "ok": False,
                "message": f"Có {len(locked_invalid)} tiết cố định xung đột với ràng buộc hoặc chế độ xếp tiết mới. Hãy bỏ cố định hoặc điều chỉnh ràng buộc trước khi xếp lại.",
            },
            409,
        )
    for lesson in invalid_lessons:
        db.delete(lesson)
    if invalid_lessons:
        db.flush()
        existing = db.scalars(select(Lesson).where(Lesson.project_id == pid)).all()

    # Tính số tiết còn thiếu theo từng phân công, không lấy tổng toàn project.
    # Cách này vẫn đúng nếu dữ liệu cũ/import từng bị lệch giữa các phân công
    # (một phân công thừa tiết trong khi phân công khác lại thiếu).
    existing_counts = Counter(lesson.assignment_id for lesson in existing)
    excess_assignment_issues = []
    for assignment in assignments:
        existing_count = existing_counts[assignment.id]
        required_count = int(assignment.periods_per_week or 0)
        if existing_count <= required_count:
            continue
        school_class = db.get(SchoolClass, assignment.class_id)
        subject = db.get(Subject, assignment.subject_id)
        teacher = db.get(Teacher, assignment.teacher_id)
        excess_assignment_issues.append(
            {
                "assignment_id": assignment.id,
                "class_name": school_class.name
                if school_class
                else f"Lớp #{assignment.class_id}",
                "subject_name": subject.name
                if subject
                else f"Môn #{assignment.subject_id}",
                "teacher_name": teacher.name
                if teacher
                else f"GV #{assignment.teacher_id}",
                "required": required_count,
                "existing": existing_count,
                "excess": existing_count - required_count,
            }
        )
    if excess_assignment_issues:
        details = "; ".join(
            f"{item['class_name']} – {item['subject_name']} ({item['existing']}/{item['required']} tiết)"
            for item in excess_assignment_issues[:5]
        )
        suffix = (
            f"; và {len(excess_assignment_issues) - 5} phân công khác"
            if len(excess_assignment_issues) > 5
            else ""
        )
        return JSONResponse(
            {
                "ok": False,
                "reason": "excess_assignment_periods",
                "excess_assignment_issues": excess_assignment_issues,
                "message": (
                    "Không thể tiếp tục xếp lịch vì có phân công đang thừa số tiết/tuần: "
                    f"{details}{suffix}. Hãy đưa bớt tiết dư về khay rồi xếp lại."
                ),
            },
            409,
        )

    missing = sum(
        int(assignment.periods_per_week or 0) - existing_counts[assignment.id]
        for assignment in assignments
    )

    # Từ lần xếp thứ hai trở đi, tuyệt đối giữ nguyên các tiết đang có.
    # Chỉ bổ sung những tiết còn thiếu trong khay; nếu lịch đã đủ thì không làm gì.
    if existing:
        if missing == 0:
            if invalid_lessons or fixed_changed:
                db.commit()
            return {
                "ok": True,
                "score": 0,
                "unscheduled": 0,
                "message": "Thời khóa biểu đã đủ tiết. Các vị trí hiện tại được giữ nguyên.",
            }
        result = solve_missing(db, p, tries=160)
        if result["unscheduled"] > 0:
            # Các tiết đang có có thể tự chặn phần còn thiếu. Thử giữ nguyên
            # tiết cố định và tái tối ưu toàn bộ phần không cố định.
            rebuild = solve_rebuild(db, p, tries=260)
            if rebuild["unscheduled"] > 0:
                if rebuild.get("proven_infeasible"):
                    message = "Các ràng buộc và tiết cố định hiện tại không cho phép tạo một thời khóa biểu đầy đủ."
                else:
                    message = (
                        f"Chưa tìm được lịch đầy đủ sau các bước bổ sung và tái tối ưu; "
                        f"còn {rebuild['unscheduled']} tiết chưa xếp. Dữ liệu lịch hiện tại chưa bị thay đổi."
                    )
                return JSONResponse(
                    {
                        "ok": False,
                        "score": rebuild["score"],
                        "unscheduled": rebuild["unscheduled"],
                        "message": message,
                    },
                    409,
                )
            current_lessons = db.scalars(
                select(Lesson).where(Lesson.project_id == pid)
            ).all()
            moved_count = sum(1 for lesson in current_lessons if not lesson.locked)
            if not payload or not payload.allow_rebuild:
                return JSONResponse(
                    {
                        "ok": False,
                        "requires_confirmation": True,
                        "moved_count": moved_count,
                        "message": (
                            "Không thể chỉ bổ sung phần còn thiếu mà giữ nguyên toàn bộ lịch hiện tại. "
                            f"Để hoàn thành thời khóa biểu, hệ thống cần xếp lại {moved_count} tiết không cố định; "
                            "các tiết cố định vẫn được giữ nguyên."
                        ),
                    },
                    409,
                )
            for lesson in current_lessons:
                if not lesson.locked:
                    db.delete(lesson)
            db.flush()
            add_generated_lessons(db, p, rebuild["lessons"])
            db.commit()
            return {
                "ok": True,
                "score": rebuild["score"],
                "unscheduled": 0,
                "message": f"Đã giữ nguyên các tiết cố định và xếp lại {moved_count} tiết không cố định để hoàn thành thời khóa biểu.",
            }
        add_generated_lessons(db, p, result["lessons"])
        db.commit()
        return {
            "ok": True,
            "score": result["score"],
            "unscheduled": 0,
            "message": f"Đã xếp bổ sung {len(result['lessons'])} tiết từ khay và giữ nguyên các vị trí còn hợp lệ.",
        }

    # Chỉ khi lịch hoàn toàn trống mới chạy bộ xếp toàn bộ.
    result = solve(db, p, tries=120)
    if result["unscheduled"] > 0:
        if result.get("proven_infeasible"):
            message = (
                "Các ràng buộc hiện tại không cho phép tạo một thời khóa biểu đầy đủ."
            )
        else:
            message = f"Chưa tìm được lịch đầy đủ sau số lần thử hiện tại; còn {result['unscheduled']} tiết chưa xếp. Lịch hiện tại được giữ nguyên."
        return JSONResponse(
            {
                "ok": False,
                "score": result["score"],
                "unscheduled": result["unscheduled"],
                "message": message,
            },
            409,
        )
    for l in existing:
        db.delete(l)
    add_generated_lessons(db, p, result["lessons"])
    db.commit()
    return {
        "ok": True,
        "score": result["score"],
        "unscheduled": 0,
        "message": f"Đã xếp đầy đủ {len(result['lessons'])} tiết.",
    }


def lesson_slot_error(
    db: Session,
    project: Project,
    assignment: Assignment,
    slot: int,
    exclude_lesson_id: Optional[int] = None,
    *,
    target_locked: bool = False,
):
    if slot not in all_slots(project):
        return "Ô thời khóa biểu không hợp lệ."
    if slot in parse_slots(project.blocked_slots_json):
        return "Buổi này đã bị khóa và không được xếp tiết."
    teacher = db.get(Teacher, assignment.teacher_id)
    school_class = db.get(SchoolClass, assignment.class_id)
    subject = db.get(Subject, assignment.subject_id)
    if not teacher or not school_class or not subject:
        return "Phân công không còn đầy đủ lớp, môn hoặc giáo viên."
    if slot in parse_slots(teacher.unavailable_json):
        return "Giáo viên không thể dạy ở tiết này theo ràng buộc chính thức."
    if slot in parse_slots(school_class.unavailable_json):
        return "Lớp không học ở tiết này."
    existing_lessons = db.scalars(
        select(Lesson).where(Lesson.project_id == project.id)
    ).all()
    existing_lessons = [
        lesson for lesson in existing_lessons if lesson.id != exclude_lesson_id
    ]
    existing_lessons = schedule_validation_peers(
        existing_lessons,
        target_locked=target_locked,
    )
    for lesson in existing_lessons:
        if lesson.slot != slot:
            continue
        other = db.get(Assignment, lesson.assignment_id)
        if other and (
            other.class_id == assignment.class_id
            or other.teacher_id == assignment.teacher_id
        ):
            return "Ô đích bị trùng lớp hoặc giáo viên."
    ppd = project.sessions * project.periods_per_session
    target_day = slot // ppd
    target_position = slot % ppd
    target_session = target_position // project.periods_per_session
    teacher_periods = 0
    subject_periods = []
    for lesson in existing_lessons:
        other = db.get(Assignment, lesson.assignment_id)
        if not other or lesson.slot // ppd != target_day:
            continue
        if other.teacher_id == assignment.teacher_id:
            teacher_periods += 1
        position = lesson.slot % ppd
        if (
            position // project.periods_per_session == target_session
            and other.class_id == assignment.class_id
            and other.subject_id == assignment.subject_id
        ):
            subject_periods.append(position % project.periods_per_session)
    if teacher_periods >= teacher.max_periods_day:
        return "Giáo viên đã đạt số tiết tối đa trong ngày."
    run = sorted(subject_periods + [target_position % project.periods_per_session])
    longest = current = 1
    for left, right in zip(run, run[1:]):
        current = current + 1 if right == left + 1 else 1
        longest = max(longest, current)
    if longest > subject.max_consecutive:
        return "Vượt số tiết liên tiếp tối đa của môn học."
    return None


class MoveIn(BaseModel):
    lesson_id: int
    slot: int


@app.post("/api/projects/{pid}/move")
def move(
    pid: int,
    payload: MoveIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    lesson = db.get(Lesson, payload.lesson_id)
    if not lesson or lesson.project_id != pid:
        raise HTTPException(404)
    fixed_slots = fixed_coverage_slots(db, project).get(lesson.assignment_id, set())
    if lesson.locked or lesson.slot in fixed_slots:
        return JSONResponse(
            {"ok": False, "message": "Tiết cố định không thể di chuyển."}, 409
        )
    assignment = db.get(Assignment, lesson.assignment_id)
    if not assignment or assignment.project_id != pid:
        return JSONResponse(
            {"ok": False, "message": "Phân công của tiết học không còn tồn tại."}, 409
        )
    error = lesson_slot_error(db, project, assignment, payload.slot, lesson.id)
    if error:
        return JSONResponse({"ok": False, "message": error}, 409)
    assignment_lessons = db.scalars(
        select(Lesson).where(Lesson.assignment_id == assignment.id)
    ).all()
    proposed_slots = [
        payload.slot if item.id == lesson.id else item.slot
        for item in assignment_lessons
    ]
    if not assignment_completion_feasible(db, project, assignment, proposed_slots):
        return JSONResponse(
            {
                "ok": False,
                "message": f"Vị trí này không thể hoàn thành hợp lệ theo chế độ {assignment_pattern_label(assignment)} và các ràng buộc hiện tại.",
            },
            409,
        )
    lesson.slot = payload.slot
    db.commit()
    return {"ok": True}


class ManualLessonIn(BaseModel):
    assignment_id: int
    slot: int


@app.post("/api/projects/{pid}/lessons")
def add_manual_lesson(
    pid: int,
    payload: ManualLessonIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    assignment = db.get(Assignment, payload.assignment_id)
    if not assignment or assignment.project_id != pid:
        raise HTTPException(404)
    scheduled = (
        db.scalar(
            select(func.count(Lesson.id)).where(Lesson.assignment_id == assignment.id)
        )
        or 0
    )
    if scheduled >= assignment.periods_per_week:
        return JSONResponse(
            {"ok": False, "message": "Phân công này đã đủ số tiết/tuần."}, 409
        )
    error = lesson_slot_error(db, project, assignment, payload.slot)
    if error:
        return JSONResponse({"ok": False, "message": error}, 409)
    current_slots = db.scalars(
        select(Lesson.slot).where(Lesson.assignment_id == assignment.id)
    ).all()
    proposed_slots = [*current_slots, payload.slot]
    if not assignment_completion_feasible(db, project, assignment, proposed_slots):
        return JSONResponse(
            {
                "ok": False,
                "message": f"Vị trí này không thể hoàn thành hợp lệ theo chế độ {assignment_pattern_label(assignment)} và các ràng buộc hiện tại.",
            },
            409,
        )
    lesson = Lesson(
        project_id=pid, assignment_id=assignment.id, slot=payload.slot, locked=False
    )
    db.add(lesson)
    db.commit()
    return {"ok": True, "id": lesson.id}


@app.delete("/api/projects/{pid}/lessons/{lesson_id}")
def remove_manual_lesson(
    pid: int,
    lesson_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    lesson = db.get(Lesson, lesson_id)
    if not lesson or lesson.project_id != pid:
        raise HTTPException(404)
    fixed_slots = fixed_coverage_slots(db, project).get(lesson.assignment_id, set())
    if lesson.locked or lesson.slot in fixed_slots:
        return JSONResponse({"ok": False, "message": "Tiết cố định không thể gỡ."}, 409)
    assignment = db.get(Assignment, lesson.assignment_id)
    if not assignment or assignment.project_id != pid:
        return JSONResponse(
            {"ok": False, "message": "Phân công của tiết học không còn tồn tại."}, 409
        )

    lessons = db.scalars(
        select(Lesson).where(Lesson.assignment_id == assignment.id)
    ).all()
    remove_ids = {lesson.id}
    if assignment_requires_double(assignment):
        slots_to_remove = required_double_removal_slots(
            [item.slot for item in lessons],
            lesson.slot,
            project.sessions,
            project.periods_per_session,
        )
        group = [item for item in lessons if item.slot in slots_to_remove]
        if any(item.locked or item.slot in fixed_slots for item in group):
            return JSONResponse(
                {
                    "ok": False,
                    "message": "Cụm tiết đôi có tiết cố định nên không thể gỡ.",
                },
                409,
            )
        remove_ids = {item.id for item in group}

    for item in lessons:
        if item.id in remove_ids:
            db.delete(item)
    db.commit()
    removed = len(remove_ids)
    message = (
        "Đã trả tiết về kho."
        if removed == 1
        else f"Đã trả cả cụm {removed} tiết về kho."
    )
    return {"ok": True, "removed": removed, "message": message}


@app.delete("/api/projects/{pid}/assignments/{assignment_id}/lessons")
def return_assignment_to_tray(
    pid: int,
    assignment_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    assignment = db.get(Assignment, assignment_id)
    if not assignment or assignment.project_id != pid:
        raise HTTPException(404)
    lessons = db.scalars(
        select(Lesson).where(
            Lesson.project_id == pid, Lesson.assignment_id == assignment_id
        )
    ).all()

    # Lesson.locked is normally the source of truth, but old/imported projects can
    # temporarily have FixedLesson metadata whose matching Lesson has not yet had
    # locked=True restored. Treat both representations as locked so the first step
    # never removes a fixed lesson and the response reports how many fixed lessons
    # were intentionally kept on the timetable.
    fixed_slots = fixed_coverage_slots(db, project).get(assignment_id, set())
    locked_lessons = [
        lesson for lesson in lessons if lesson.locked or lesson.slot in fixed_slots
    ]
    locked_ids = {lesson.id for lesson in locked_lessons}
    removable = [lesson for lesson in lessons if lesson.id not in locked_ids]

    for lesson in removable:
        db.delete(lesson)
    db.commit()
    locked = len(locked_lessons)
    message = f"Đã đưa {len(removable)} tiết chưa cố định về khay."
    if locked:
        message += f" Giữ nguyên {locked} tiết đã cố định."
    return {"ok": True, "removed": len(removable), "locked": locked, "message": message}


@app.delete("/api/projects/{pid}/lessons")
def return_all_to_tray(
    pid: int, user: User = Depends(current_user), db: Session = Depends(db_session)
):
    project = get_project_for_update(pid, user, db)
    lessons = db.scalars(select(Lesson).where(Lesson.project_id == pid)).all()
    fixed_slots = fixed_coverage_slots(db, project)
    removable = [
        lesson
        for lesson in lessons
        if not lesson.locked
        and lesson.slot not in fixed_slots.get(lesson.assignment_id, set())
    ]
    removable_ids = {lesson.id for lesson in removable}
    fixed_count = sum(1 for lesson in lessons if lesson.id not in removable_ids)
    for lesson in removable:
        db.delete(lesson)
    db.commit()
    message = f"Đã đưa {len(removable)} tiết chưa cố định về khay."
    if fixed_count:
        message += f" Giữ nguyên {fixed_count} tiết đã cố định."
    return {
        "ok": True,
        "removed": len(removable),
        "locked": fixed_count,
        "message": message,
    }


@app.get("/api/projects/{pid}/data")
def api_data(
    pid: int,
    parts: Optional[str] = None,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    p = get_project(pid, user, db)
    requested = {item.strip() for item in (parts or "").split(",") if item.strip()}
    if not requested:
        return project_data(db, p)
    unknown = requested - {"lessons"}
    if unknown:
        raise HTTPException(400, f"Phần dữ liệu không hỗ trợ: {', '.join(sorted(unknown))}")
    result = {}
    if "lessons" in requested:
        result["lessons"] = project_lessons_data(db, p.id)
    return result


def teacher_view_projects(user: User, db: Session) -> list[Project]:
    if user.role != "teacher":
        raise HTTPException(403, "Tài khoản giáo viên không hợp lệ")
    school_ids = user_school_ids(user, db)
    if not school_ids:
        return []
    return db.scalars(
        select(Project)
        .where(Project.school_id.in_(school_ids))
        .order_by(Project.id.desc())
    ).all()


def teacher_view_project(
    user: User, db: Session, project_id: Optional[int] = None
) -> Project | None:
    projects = teacher_view_projects(user, db)
    if not projects:
        return None
    if project_id is None:
        return projects[0]
    for project in projects:
        if project.id == project_id:
            return project
    raise HTTPException(404, "Không tìm thấy bộ thời khóa biểu")


@app.get("/teacher", response_class=HTMLResponse)
def teacher_portal(
    request: Request,
    project_id: Optional[int] = None,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    teacher_schools = user_schools(user, db)
    projects = teacher_view_projects(user, db)
    if not projects:
        return templates.TemplateResponse(
            "teacher_empty.html",
            {
                "request": request,
                "user": user,
                "teacher_schools": teacher_schools,
            },
        )
    project = teacher_view_project(user, db, project_id)
    preference_history = teacher_own_preference_payload(db, project, user.id)
    current_preference = next(
        (item for item in preference_history if item["status"] == "pending"), None
    )
    return templates.TemplateResponse(
        "teacher_portal.html",
        {
            "request": request,
            "user": user,
            "p": project,
            "data": public_project_data(db, project),
            "days": DAYS,
            "teacher_projects": projects,
            "preference_history": preference_history,
            "current_preference": current_preference,
            "preference_saved": request.query_params.get("preference_saved") == "1",
            **chatbot_ui_context(project),
        },
    )


@app.get("/api/teacher/data")
def api_teacher_data(
    project_id: Optional[int] = None,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = teacher_view_project(user, db, project_id)
    if not project:
        raise HTTPException(404, "Chưa có bộ thời khóa biểu nào")
    return public_project_data(db, project)


@app.get("/teacher/account", response_class=HTMLResponse)
def teacher_account_page(
    request: Request,
    project_id: Optional[int] = None,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if user.role != "teacher":
        raise HTTPException(403, "Tài khoản giáo viên không hợp lệ")
    project = db.get(Project, project_id) if project_id is not None else None
    if project_id is not None and (
        not project or not user_can_access_school(user, project.school_id, db)
    ):
        raise HTTPException(404, "Không tìm thấy bộ thời khóa biểu")
    return templates.TemplateResponse(
        "teacher_account.html",
        {
            "request": request,
            "user": user,
            "p": project,
            "error": None,
            "success": None,
            **chatbot_ui_context(project),
        },
    )


@app.post("/teacher/account/password", response_class=HTMLResponse)
def update_teacher_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    project_id: Optional[int] = Form(None),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if user.role != "teacher":
        raise HTTPException(403, "Tài khoản giáo viên không hợp lệ")
    project = db.get(Project, project_id) if project_id is not None else None
    if project_id is not None and (
        not project or not user_can_access_school(user, project.school_id, db)
    ):
        raise HTTPException(404, "Không tìm thấy bộ thời khóa biểu")
    context = {
        "request": request,
        "user": user,
        "p": project,
        "error": None,
        "success": None,
        **chatbot_ui_context(project),
    }
    if not pwd.verify(current_password, user.password_hash):
        context["error"] = "Mật khẩu hiện tại không đúng."
        return templates.TemplateResponse(
            "teacher_account.html", context, status_code=400
        )
    if len(new_password) < MIN_PASSWORD_LENGTH:
        context["error"] = f"Mật khẩu mới phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự."
        return templates.TemplateResponse(
            "teacher_account.html", context, status_code=400
        )
    if new_password != confirm_password:
        context["error"] = "Xác nhận mật khẩu mới không khớp."
        return templates.TemplateResponse(
            "teacher_account.html", context, status_code=400
        )
    if pwd.verify(new_password, user.password_hash):
        context["error"] = "Mật khẩu mới phải khác mật khẩu hiện tại."
        return templates.TemplateResponse(
            "teacher_account.html", context, status_code=400
        )

    user.password_hash = pwd.hash(new_password)
    user.session_version += 1
    db.commit()
    context["user"] = user
    context["success"] = "Mật khẩu đã được thay đổi thành công."
    response = templates.TemplateResponse("teacher_account.html", context)
    set_session_cookie(response, user)
    return response


def email_change_target(account_id: str, actor: User, db: Session) -> User:
    raw = str(account_id or "").strip()
    if not raw:
        return actor
    try:
        target_id = int(raw)
    except ValueError as exc:
        raise HTTPException(400, "Tài khoản cần đổi email không hợp lệ") from exc
    target = db.get(User, target_id)
    if not target or not admin_can_manage_account(actor, target, db):
        raise HTTPException(404, "Không tìm thấy tài khoản trong phạm vi quản lý")
    return target


def email_change_back_path(actor: User, project_id: Optional[int] = None) -> str:
    if actor.role == "teacher":
        return (
            f"/teacher/account?project_id={project_id}"
            if project_id is not None
            else "/teacher/account"
        )
    return "/admin/users"


def email_change_confirmation_data(
    token: str, actor: User, db: Session
) -> tuple[User, str, Optional[int]]:
    try:
        data = email_change_signer.loads(
            token, max_age=EMAIL_CHANGE_CONFIRM_TTL_SECONDS
        )
        if int(data["actor_id"]) != actor.id:
            raise HTTPException(
                403, "Phiên xác nhận đổi email không thuộc tài khoản này"
            )
        target = db.get(User, int(data["account_id"]))
        if not target:
            raise HTTPException(404, "Tài khoản không còn tồn tại")
        if target.id != actor.id and not admin_can_manage_account(actor, target, db):
            raise HTTPException(403, "Bạn không còn quyền đổi email tài khoản này")
        new_email = str(data["new_email"]).lower().strip()
        project_id = data.get("project_id")
        return target, new_email, int(project_id) if project_id is not None else None
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            400, "Phiên xác nhận đổi email không hợp lệ hoặc đã hết hạn"
        ) from exc


def email_change_verification_for_token(
    token: str, actor: User, db: Session
) -> EmailChangeVerification | None:
    try:
        data = email_change_otp_signer.loads(
            token, max_age=EMAIL_CHANGE_OTP_TTL_SECONDS
        )
        row = db.scalar(
            select(EmailChangeVerification)
            .where(EmailChangeVerification.id == int(data["id"]))
            .with_for_update()
        )
        if not row or row.requested_by_user_id != actor.id:
            return None
        nonce_hash = hashlib.sha256(str(data["nonce"]).encode()).hexdigest()
        if not hmac.compare_digest(row.token_hash, nonce_hash):
            return None
        return row
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None


@app.get("/account/email-change", response_class=HTMLResponse)
def email_change_page(
    request: Request,
    project_id: Optional[int] = None,
    user: User = Depends(current_user),
):
    return templates.TemplateResponse(
        "email_change.html",
        {
            "request": request,
            "mode": "start",
            "user": user,
            "target": user,
            "project_id": project_id,
            "error": None,
            "back_path": email_change_back_path(user, project_id),
        },
    )


@app.post("/account/email-change/prepare", response_class=HTMLResponse)
def prepare_email_change(
    request: Request,
    email: str = Form(...),
    current_password: str = Form(""),
    account_id: str = Form(""),
    project_id: Optional[int] = Form(None),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    target = email_change_target(account_id, user, db)
    new_email = bounded_text(email.lower(), "Email mới", 255)
    back_path = email_change_back_path(user, project_id)
    context = {
        "request": request,
        "mode": "start",
        "user": user,
        "target": target,
        "project_id": project_id,
        "error": None,
        "back_path": back_path,
    }
    if "@" not in new_email:
        context["error"] = "Email mới không hợp lệ."
        return templates.TemplateResponse("email_change.html", context, status_code=400)
    if new_email == target.email.lower().strip():
        context["error"] = "Email mới phải khác email hiện tại."
        return templates.TemplateResponse("email_change.html", context, status_code=400)
    if target.id == user.id and (
        not current_password or not pwd.verify(current_password, target.password_hash)
    ):
        context["error"] = "Vui lòng nhập đúng mật khẩu hiện tại trước khi đổi email."
        return templates.TemplateResponse("email_change.html", context, status_code=400)
    if (
        db.scalar(
            select(User.id).where(
                func.lower(User.email) == new_email, User.id != target.id
            )
        )
        is not None
    ):
        context["error"] = "Email mới đã được sử dụng bởi tài khoản khác."
        return templates.TemplateResponse("email_change.html", context, status_code=409)
    confirmation_token = email_change_signer.dumps(
        {
            "actor_id": user.id,
            "account_id": target.id,
            "new_email": new_email,
            "project_id": project_id,
        }
    )
    return templates.TemplateResponse(
        "email_change.html",
        {
            "request": request,
            "mode": "confirm",
            "user": user,
            "target": target,
            "new_email": new_email,
            "confirmation_token": confirmation_token,
            "back_path": back_path,
            "error": None,
        },
    )


@app.post("/account/email-change/confirm", response_class=HTMLResponse)
def confirm_email_change(
    request: Request,
    confirmation_token: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    target, new_email, project_id = email_change_confirmation_data(
        confirmation_token, user, db
    )
    back_path = email_change_back_path(user, project_id)
    if (
        db.scalar(
            select(User.id).where(
                func.lower(User.email) == new_email, User.id != target.id
            )
        )
        is not None
    ):
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "confirm",
                "user": user,
                "target": target,
                "new_email": new_email,
                "confirmation_token": confirmation_token,
                "back_path": back_path,
                "error": "Email mới vừa được tài khoản khác sử dụng.",
            },
            status_code=409,
        )
    if rate_limit_exceeded(
        "email_change_actor", str(user.id), limit=5, window_seconds=15 * 60
    ) or rate_limit_exceeded(
        "email_change_target", new_email, limit=5, window_seconds=15 * 60
    ):
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "confirm",
                "user": user,
                "target": target,
                "new_email": new_email,
                "confirmation_token": confirmation_token,
                "back_path": back_path,
                "error": "Bạn đã yêu cầu đổi email quá nhiều lần. Vui lòng thử lại sau.",
            },
            status_code=429,
        )
    otp = f"{secrets.randbelow(1_000_000):06d}"
    try:
        if not send_email_change_otp_email(new_email, otp):
            raise RuntimeError("SMTP chưa được cấu hình")
    except (OSError, smtplib.SMTPException, RuntimeError, ValueError) as exc:
        logger.exception("Could not send email-change OTP to %s: %s", new_email, exc)
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "confirm",
                "user": user,
                "target": target,
                "new_email": new_email,
                "confirmation_token": confirmation_token,
                "back_path": back_path,
                "error": "Chưa thể gửi OTP tới email mới. Vui lòng thử lại sau.",
            },
            status_code=503,
        )
    old = db.scalar(
        select(EmailChangeVerification)
        .where(EmailChangeVerification.user_id == target.id)
        .with_for_update()
    )
    if old:
        db.delete(old)
        db.flush()
    nonce = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    verification = EmailChangeVerification(
        user_id=target.id,
        requested_by_user_id=user.id,
        new_email=new_email,
        otp_hash=email_change_otp_hash(target.id, new_email, otp),
        token_hash=hashlib.sha256(nonce.encode()).hexdigest(),
        expires_at=(now + timedelta(seconds=EMAIL_CHANGE_OTP_TTL_SECONDS)).isoformat(),
        attempt_count=0,
    )
    db.add(verification)
    db.commit()
    verification_token = email_change_otp_signer.dumps(
        {"id": verification.id, "nonce": nonce}
    )
    return templates.TemplateResponse(
        "email_change.html",
        {
            "request": request,
            "mode": "otp",
            "user": user,
            "target": target,
            "masked_email": mask_email(new_email),
            "verification_token": verification_token,
            "back_path": back_path,
            "error": None,
        },
    )


@app.post("/account/email-change/verify", response_class=HTMLResponse)
def verify_email_change(
    request: Request,
    verification_token: str = Form(...),
    otp: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    verification = email_change_verification_for_token(verification_token, user, db)
    if not verification:
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "expired",
                "user": user,
                "back_path": email_change_back_path(user),
                "error": "Phiên xác minh email không hợp lệ hoặc đã hết hạn.",
            },
            status_code=400,
        )
    target = db.get(User, verification.user_id)
    if not target or (
        target.id != user.id and not admin_can_manage_account(user, target, db)
    ):
        raise HTTPException(403, "Bạn không còn quyền đổi email tài khoản này")
    now = datetime.now(timezone.utc)
    if datetime.fromisoformat(verification.expires_at) <= now:
        db.delete(verification)
        db.commit()
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "expired",
                "user": user,
                "back_path": email_change_back_path(user),
                "error": "Mã OTP đã hết hạn. Hãy bắt đầu lại thao tác đổi email.",
            },
            status_code=400,
        )
    if verification.attempt_count >= EMAIL_CHANGE_OTP_MAX_ATTEMPTS:
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "expired",
                "user": user,
                "back_path": email_change_back_path(user),
                "error": "Bạn đã nhập sai quá số lần cho phép. Hãy bắt đầu lại thao tác đổi email.",
            },
            status_code=429,
        )
    normalized_otp = otp.strip()
    if (
        not normalized_otp.isdigit()
        or len(normalized_otp) != 6
        or not hmac.compare_digest(
            verification.otp_hash,
            email_change_otp_hash(target.id, verification.new_email, normalized_otp),
        )
    ):
        verification.attempt_count += 1
        remaining = max(0, EMAIL_CHANGE_OTP_MAX_ATTEMPTS - verification.attempt_count)
        db.commit()
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "otp",
                "user": user,
                "target": target,
                "masked_email": mask_email(verification.new_email),
                "verification_token": verification_token,
                "back_path": email_change_back_path(user),
                "error": f"Mã OTP không đúng. Bạn còn {remaining} lần thử.",
            },
            status_code=400,
        )
    if (
        db.scalar(
            select(User.id).where(
                func.lower(User.email) == verification.new_email, User.id != target.id
            )
        )
        is not None
    ):
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "expired",
                "user": user,
                "back_path": email_change_back_path(user),
                "error": "Email mới vừa được tài khoản khác sử dụng. Hãy chọn email khác.",
            },
            status_code=409,
        )
    target.email = verification.new_email
    target.session_version += 1
    db.delete(verification)
    db.commit()
    response = templates.TemplateResponse(
        "email_change.html",
        {
            "request": request,
            "mode": "success",
            "user": target if target.id == user.id else user,
            "target": target,
            "back_path": email_change_back_path(user),
            "error": None,
        },
    )
    if target.id == user.id:
        set_session_cookie(response, target)
    return response


@app.get("/share/{token}", response_class=HTMLResponse)
def shared(token: str, request: Request, db: Session = Depends(db_session)):
    p = db.scalar(select(Project).where(Project.share_token == token))
    if not p:
        raise HTTPException(404)
    return templates.TemplateResponse(
        "share.html",
        {"request": request, "p": p, "data": public_project_data(db, p), "days": DAYS},
    )


def teacher_own_preference_payload(
    db: Session, project: Project, user_id: int
) -> list[dict]:
    rows = db.scalars(
        select(TeacherPreference)
        .where(
            TeacherPreference.project_id == project.id,
            TeacherPreference.submitted_by_user_id == user_id,
        )
        .order_by(TeacherPreference.id.desc())
        .limit(10)
    ).all()

    def label(slot: int) -> str:
        day, session, period = slot_meta(project, slot)
        session_text = (
            f"{'Sáng' if session == 0 else 'Chiều'} · " if project.sessions > 1 else ""
        )
        return f"{DAYS[day]} · {session_text}Tiết {period + 1}"

    items = []
    for row in rows:
        preferred = valid_slots(project, parse_slots(row.preferred_json), strict=False)
        unavailable = valid_slots(
            project, parse_slots(row.unavailable_json), strict=False
        )
        items.append(
            {
                "id": row.id,
                "preferred_slots": preferred,
                "unavailable_slots": unavailable,
                "preferred_labels": [label(slot) for slot in preferred],
                "unavailable_labels": [label(slot) for slot in unavailable],
                "note": row.note,
                "status": row.status,
                "created_at": row.created_at,
                "created_at_display": format_vietnam_datetime(row.created_at),
            }
        )
    return items


@app.post("/teacher/preferences")
def submit_teacher_preference(
    project_id: int = Form(...),
    preferred_slots: str = Form("[]"),
    unavailable_slots: str = Form("[]"),
    note: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if user.role != "teacher":
        raise HTTPException(403, "Chỉ tài khoản giáo viên được gửi nguyện vọng")
    project = teacher_view_project(user, db, project_id)
    if not project:
        raise HTTPException(404, "Không tìm thấy bộ thời khóa biểu")
    try:
        preferred_raw = json.loads(preferred_slots)
        unavailable_raw = json.loads(unavailable_slots)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(400, "Danh sách tiết nguyện vọng không hợp lệ") from exc
    preferred = valid_slots(project, preferred_raw, strict=True)
    unavailable = valid_slots(project, unavailable_raw, strict=True)
    overlap = sorted(set(preferred) & set(unavailable))
    if overlap:
        raise HTTPException(400, "Một tiết không thể vừa là mong muốn vừa là cần tránh")
    note = bounded_text(note, "Ghi chú", 2000, required=False)
    if not preferred and not unavailable and not note:
        raise HTTPException(
            400, "Hãy chọn ít nhất một tiết hoặc nhập ghi chú nguyện vọng"
        )
    # Mỗi lần gửi mới chỉ thay thế nguyện vọng đang chờ trước đó của chính tài
    # khoản này. Khóa row tài khoản để hai request đồng thời không thể cùng
    # nhìn thấy "không có pending" rồi tạo ra hai nguyện vọng đang chờ.
    # Không ghi sang Teacher.unavailable_json, không tạo constraint và không
    # gọi bất kỳ hàm xếp lịch nào.
    db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    pending_rows = db.scalars(
        select(TeacherPreference)
        .where(
            TeacherPreference.project_id == project.id,
            TeacherPreference.submitted_by_user_id == user.id,
            TeacherPreference.status == "pending",
        )
        .with_for_update()
    ).all()
    now_text = _utc_now_iso()
    for old in pending_rows:
        old.status = "superseded"
        old.reviewed_at = now_text
    db.add(
        TeacherPreference(
            project_id=project.id,
            teacher_id=None,
            submitted_by_user_id=user.id,
            submitted_name=user.name,
            submitted_email=user.email,
            preferred_json=json.dumps(preferred),
            unavailable_json=json.dumps(unavailable),
            note=note,
            status="pending",
        )
    )
    db.commit()
    return RedirectResponse(
        f"/teacher?project_id={project.id}&preference_saved=1#teacher-preferences", 303
    )


def preference_payload(db: Session, p: Project):
    rows = db.scalars(
        select(TeacherPreference)
        .where(TeacherPreference.project_id == p.id)
        .order_by(TeacherPreference.id.desc())
    ).all()
    teachers = {
        x.id: x for x in db.scalars(select(Teacher).where(Teacher.project_id == p.id))
    }

    def label(slot: int):
        day, session, period = slot_meta(p, slot)
        session_text = (
            f"{'Sáng' if session == 0 else 'Chiều'} · " if p.sessions > 1 else ""
        )
        return f"{DAYS[day]} · {session_text}Tiết {period + 1}"

    items = []
    for row in rows:
        preferred_slots = valid_slots(p, parse_slots(row.preferred_json), strict=False)
        unavailable_slots = valid_slots(
            p, parse_slots(row.unavailable_json), strict=False
        )
        items.append(
            {
                "id": row.id,
                "teacher_id": row.teacher_id,
                "teacher_name": row.submitted_name
                or (
                    teachers[row.teacher_id].name if row.teacher_id in teachers else "?"
                ),
                "teacher_email": row.submitted_email or "",
                "preferred_slots": preferred_slots,
                "unavailable_slots": unavailable_slots,
                "preferred_labels": [label(slot) for slot in preferred_slots],
                "unavailable_labels": [label(slot) for slot in unavailable_slots],
                "note": row.note,
                "status": row.status,
                "created_at": row.created_at,
                "created_at_display": format_vietnam_datetime(row.created_at),
                "reviewed_at": row.reviewed_at,
                "reviewed_at_display": format_vietnam_datetime(row.reviewed_at),
            }
        )
    return items


@app.get("/api/projects/{pid}/preferences")
def list_teacher_preferences(
    pid: int, user: User = Depends(current_user), db: Session = Depends(db_session)
):
    p = get_project(pid, user, db)
    return {"items": preference_payload(db, p)}


@app.delete("/api/projects/{pid}/preferences/{preference_id}")
def delete_teacher_preference(
    pid: int,
    preference_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    get_project_for_update(pid, user, db)
    preference = db.scalar(
        select(TeacherPreference)
        .where(
            TeacherPreference.id == preference_id,
            TeacherPreference.project_id == pid,
        )
        .with_for_update()
    )
    if not preference:
        raise HTTPException(404, "Không tìm thấy nguyện vọng")
    db.delete(preference)
    db.commit()
    return {"ok": True, "message": "Đã xóa nguyện vọng."}


@app.delete("/api/projects/{pid}/preferences")
def delete_all_teacher_preferences(
    pid: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    get_project_for_update(pid, user, db)
    rows = db.scalars(
        select(TeacherPreference)
        .where(TeacherPreference.project_id == pid)
        .with_for_update()
    ).all()
    deleted = len(rows)
    for preference in rows:
        db.delete(preference)
    db.commit()
    return {
        "ok": True,
        "deleted": deleted,
        "message": f"Đã xóa {deleted} nguyện vọng." if deleted else "Không có nguyện vọng để xóa.",
    }


class PreferenceReviewIn(BaseModel):
    action: str


@app.post("/api/projects/{pid}/preferences/{preference_id}/review")
def review_teacher_preference(
    pid: int,
    preference_id: int,
    payload: PreferenceReviewIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    get_project(pid, user, db)
    preference = db.scalar(
        select(TeacherPreference)
        .where(
            TeacherPreference.id == preference_id,
            TeacherPreference.project_id == pid,
        )
        .with_for_update()
    )
    if not preference:
        raise HTTPException(404, "Không tìm thấy nguyện vọng")
    if payload.action not in {"accept", "reject"}:
        raise HTTPException(400, "Thao tác không hợp lệ")
    if preference.status != "pending":
        raise HTTPException(409, "Nguyện vọng này đã được xử lý")

    # Nguyện vọng chỉ là dữ liệu tham khảo. Việc ghi nhận/từ chối không được
    # sửa lịch, không tạo constraint và không ảnh hưởng bất kỳ solver nào.
    preference.status = "accepted" if payload.action == "accept" else "rejected"
    preference.reviewed_at = _utc_now_iso()
    db.commit()
    return {
        "ok": True,
        "message": (
            "Đã ghi nhận nguyện vọng để tham khảo; thời khóa biểu không bị thay đổi."
            if payload.action == "accept"
            else "Đã từ chối nguyện vọng; thời khóa biểu không bị thay đổi."
        ),
    }


@app.get("/projects/{pid}/export.csv", include_in_schema=False)
def export_csv_legacy(
    pid: int, user: User = Depends(current_user), db: Session = Depends(db_session)
):
    get_project(pid, user, db)
    return RedirectResponse(f"/projects/{pid}/export.xlsx", 303)


@app.get("/projects/{pid}/export.xlsx")
def export_excel(
    pid: int, user: User = Depends(current_user), db: Session = Depends(db_session)
):
    from app.excel_export import build_timetable_workbook

    p = get_project(pid, user, db)
    data = project_data(db, p)
    workbook = build_timetable_workbook(p, data)

    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    encoded_filename = quote(f"{p.name}.xlsx", safe="")
    disposition = (
        f"attachment; filename=thoi-khoa-bieu.xlsx; filename*=UTF-8''{encoded_filename}"
    )
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": disposition},
    )


def project_lessons_data(db: Session, project_id: int):
    project = db.get(Project, project_id)
    fixed_slots = fixed_coverage_slots(db, project) if project else {}
    return [
        {
            "id": row.id,
            "assignment_id": row.assignment_id,
            "slot": row.slot,
            "locked": bool(
                row.locked
                or row.slot in fixed_slots.get(row.assignment_id, set())
            ),
        }
        for row in db.scalars(
            select(Lesson).where(Lesson.project_id == project_id)
        ).all()
    ]


def project_data(db: Session, p: Project):
    deps = db.scalars(select(Department).where(Department.project_id == p.id)).all()
    subs = db.scalars(select(Subject).where(Subject.project_id == p.id)).all()
    teas = db.scalars(select(Teacher).where(Teacher.project_id == p.id)).all()
    grades = db.scalars(select(Grade).where(Grade.project_id == p.id)).all()
    grade_requirements = db.scalars(
        select(GradeSubjectRequirement).where(
            GradeSubjectRequirement.project_id == p.id
        )
    ).all()
    classes = db.scalars(
        select(SchoolClass).where(SchoolClass.project_id == p.id)
    ).all()
    assignments = db.scalars(
        select(Assignment).where(Assignment.project_id == p.id)
    ).all()
    lessons = db.scalars(select(Lesson).where(Lesson.project_id == p.id)).all()
    fixed_slots = fixed_coverage_slots(db, p)
    sm = {x.id: x for x in subs}
    tm = {x.id: x for x in teas}
    cm = {x.id: x for x in classes}
    teacher_subject_rows = db.scalars(
        select(TeacherSubject).where(TeacherSubject.project_id == p.id)
    ).all()
    teacher_subject_map = defaultdict(list)
    for row in teacher_subject_rows:
        teacher_subject_map[row.teacher_id].append(row.subject_id)
    teacher_loads = Counter()
    for assignment in assignments:
        teacher_loads[assignment.teacher_id] += assignment.periods_per_week
    capacity_issues = schedule_teacher_capacity_issues(db, p, assignments)
    class_capacity_issues = schedule_class_capacity_issues(p, classes, assignments)
    duplicate_issues = duplicate_assignment_issues(db, assignments)
    assigned_teacher_ids = {x.teacher_id for x in assignments}
    assigned_subject_ids = {x.subject_id for x in assignments}
    assigned_class_ids = {x.class_id for x in assignments}
    return {
        "project": {
            "id": p.id,
            "name": p.name,
            "school_name": p.school_name,
            "days": p.days,
            "sessions": p.sessions,
            "periods": p.periods_per_session,
            "share_token": p.share_token,
            "blocked_slots": valid_slots(
                p, parse_slots(p.blocked_slots_json), strict=False
            ),
        },
        "departments": [{"id": x.id, "name": x.name} for x in deps],
        "subjects": [
            {
                "id": x.id,
                "name": x.name,
                "short_name": x.short_name,
                "max_consecutive": x.max_consecutive,
            }
            for x in subs
        ],
        "teachers": [
            {
                "id": x.id,
                "name": x.name,
                "short_name": x.short_name,
                "department_id": x.department_id,
                "max_periods_day": x.max_periods_day,
                "unavailable": list(parse_slots(x.unavailable_json)),
                "subject_ids": sorted(teacher_subject_map.get(x.id, [])),
                "assigned_periods": teacher_loads.get(x.id, 0),
                "week_capacity": teacher_week_capacity(p, x),
            }
            for x in teas
        ],
        "grades": [{"id": x.id, "name": x.name} for x in grades],
        "grade_requirements": [
            {
                "id": x.id,
                "grade_id": x.grade_id,
                "subject_id": x.subject_id,
                "periods_per_week": x.periods_per_week,
                "block_mode": x.block_mode,
            }
            for x in grade_requirements
        ],
        "classes": [
            {
                "id": x.id,
                "name": x.name,
                "grade_id": x.grade_id,
                "unavailable": list(parse_slots(x.unavailable_json)),
            }
            for x in classes
        ],
        "assignments": [
            {
                "id": x.id,
                "class_id": x.class_id,
                "subject_id": x.subject_id,
                "teacher_id": x.teacher_id,
                "periods_per_week": x.periods_per_week,
                "block_mode": x.block_mode,
                "class_name": cm.get(x.class_id).name if cm.get(x.class_id) else "?",
                "subject_name": sm.get(x.subject_id).name
                if sm.get(x.subject_id)
                else "?",
                "subject_short": sm.get(x.subject_id).short_name
                if sm.get(x.subject_id)
                else "?",
                "teacher_name": tm.get(x.teacher_id).name
                if tm.get(x.teacher_id)
                else "?",
                "teacher_short": tm.get(x.teacher_id).short_name
                if tm.get(x.teacher_id)
                else "?",
            }
            for x in assignments
        ],
        "lessons": [
            {
                "id": x.id,
                "assignment_id": x.assignment_id,
                "slot": x.slot,
                "locked": bool(
                    x.locked
                    or x.slot in fixed_slots.get(x.assignment_id, set())
                ),
            }
            for x in lessons
        ],
        "coverage": {
            "duplicate_assignments": duplicate_issues,
            "over_capacity_teachers": capacity_issues,
            "over_capacity_classes": class_capacity_issues,
            "unassigned_teachers": [
                {"id": x.id, "name": x.name}
                for x in teas
                if x.id not in assigned_teacher_ids
            ],
            "unassigned_subjects": [
                {"id": x.id, "name": x.name}
                for x in subs
                if x.id not in assigned_subject_ids
            ],
            "unassigned_classes": [
                {"id": x.id, "name": x.name}
                for x in classes
                if x.id not in assigned_class_ids
            ],
        },
    }


def public_project_data(db: Session, p: Project):
    subjects = {
        x.id: x
        for x in db.scalars(select(Subject).where(Subject.project_id == p.id)).all()
    }
    teachers = {
        x.id: x
        for x in db.scalars(select(Teacher).where(Teacher.project_id == p.id)).all()
    }
    classes = {
        x.id: x
        for x in db.scalars(
            select(SchoolClass).where(SchoolClass.project_id == p.id)
        ).all()
    }
    assignments = db.scalars(
        select(Assignment).where(Assignment.project_id == p.id)
    ).all()
    lessons = db.scalars(select(Lesson).where(Lesson.project_id == p.id)).all()
    return {
        "project": {
            "id": p.id,
            "name": p.name,
            "school_name": p.school_name,
            "days": p.days,
            "sessions": p.sessions,
            "periods": p.periods_per_session,
            "blocked_slots": valid_slots(
                p, parse_slots(p.blocked_slots_json), strict=False
            ),
        },
        "classes": [{"id": item.id, "name": item.name} for item in classes.values()],
        "teachers": [
            {"id": item.id, "name": item.name, "short_name": item.short_name}
            for item in teachers.values()
        ],
        "subjects": [
            {"id": item.id, "name": item.name, "short_name": item.short_name}
            for item in subjects.values()
        ],
        "assignments": [
            {
                "id": item.id,
                "class_id": item.class_id,
                "subject_id": item.subject_id,
                "teacher_id": item.teacher_id,
                "periods_per_week": item.periods_per_week,
                "block_mode": item.block_mode,
                "class_name": classes[item.class_id].name
                if item.class_id in classes
                else "?",
                "subject_name": subjects[item.subject_id].name
                if item.subject_id in subjects
                else "?",
                "subject_short": subjects[item.subject_id].short_name
                if item.subject_id in subjects
                else "?",
                "teacher_name": teachers[item.teacher_id].name
                if item.teacher_id in teachers
                else "?",
                "teacher_short": teachers[item.teacher_id].short_name
                if item.teacher_id in teachers
                else "?",
            }
            for item in assignments
        ],
        "lessons": [
            {"id": item.id, "assignment_id": item.assignment_id, "slot": item.slot}
            for item in lessons
        ],
    }


def ga_schedule(
    db: Session,
    p: Project,
    mode: str,
    tries: int = 120,
    target_assignment_ids: Optional[set[int]] = None,
):
    assignments = db.scalars(
        select(Assignment).where(Assignment.project_id == p.id)
    ).all()
    teachers = {
        x.id: x for x in db.scalars(select(Teacher).where(Teacher.project_id == p.id))
    }
    classes = {
        x.id: x
        for x in db.scalars(select(SchoolClass).where(SchoolClass.project_id == p.id))
    }
    subjects = {
        x.id: x for x in db.scalars(select(Subject).where(Subject.project_id == p.id))
    }
    all_existing = db.scalars(select(Lesson).where(Lesson.project_id == p.id)).all()
    relevant_assignments = (
        assignments
        if target_assignment_ids is None
        else [row for row in assignments if row.id in target_assignment_ids]
    )
    invalid_reference_ids = sorted(
        row.id
        for row in relevant_assignments
        if row.teacher_id not in teachers
        or row.class_id not in classes
        or row.subject_id not in subjects
    )
    if invalid_reference_ids:
        invalid_reference_id_set = set(invalid_reference_ids)
        missing = sum(
            max(1, int(row.periods_per_week or 0))
            for row in relevant_assignments
            if row.id in invalid_reference_id_set
        )
        return {
            "lessons": [],
            "unscheduled": missing,
            "score": missing * 10000,
            "invalid_assignments": invalid_reference_ids,
            "invalid_reference_assignments": invalid_reference_ids,
        }
    if mode == "missing":
        existing = list(all_existing)
    elif mode == "rebuild":
        existing = [lesson for lesson in all_existing if lesson.locked]
    elif mode == "full":
        existing = []
    else:
        raise ValueError(f"Chế độ xếp lịch không hợp lệ: {mode}")
    existing_counts = Counter(x.assignment_id for x in existing)
    existing_slots = defaultdict(set)
    locked_slots = defaultdict(set)
    for lesson in existing:
        existing_slots[lesson.assignment_id].add(lesson.slot)
        if lesson.locked:
            locked_slots[lesson.assignment_id].add(lesson.slot)
    fixed_rows_by_assignment = defaultdict(list)
    for row in db.scalars(
        select(FixedLesson).where(FixedLesson.project_id == p.id)
    ).all():
        assignment = next(
            (item for item in assignments if item.id == row.assignment_id), None
        )
        if assignment:
            size = fixed_row_size(
                p,
                assignment,
                row,
                [
                    lesson
                    for lesson in all_existing
                    if lesson.assignment_id == assignment.id
                ],
            )
            fixed_rows_by_assignment[row.assignment_id].append((row.slot, size))
    invalid_fixed_assignment_ids = set()
    for assignment in assignments:
        fixed_error = fixed_group_validation_error(
            assignment_groups(assignment),
            fixed_rows_by_assignment[assignment.id],
            days=p.days,
            sessions=p.sessions,
            periods_per_session=p.periods_per_session,
        )
        if fixed_error and (
            target_assignment_ids is None or assignment.id in target_assignment_ids
        ):
            invalid_fixed_assignment_ids.add(assignment.id)
    global_blocked = parse_slots(p.blocked_slots_json)
    slots = all_slots(p)
    ppd = p.sessions * p.periods_per_session
    if not assignments:
        return {"lessons": [], "unscheduled": 0, "score": 0}

    task_rows = []
    invalid_assignment_ids = []
    for assignment in assignments:
        if (
            target_assignment_ids is not None
            and assignment.id not in target_assignment_ids
        ):
            continue
        if assignment.id in invalid_fixed_assignment_ids:
            continue
        current_slots = (
            existing_slots[assignment.id] if mode in {"missing", "rebuild"} else set()
        )
        plan = pattern_completion_plan(p, assignment, current_slots)
        if plan is None:
            invalid_assignment_ids.append(assignment.id)
            continue
        pending = [dict(item) for item in plan]
        task_index = 0
        for fixed_slot, fixed_size in fixed_rows_by_assignment[assignment.id]:
            expected = set(range(fixed_slot, fixed_slot + fixed_size))
            if expected.issubset(locked_slots[assignment.id]):
                continue

            # Một cụm cố định có thể chỉ còn lại một phần trên lịch. Khi đó
            # pattern_completion_plan() trả về task có anchor_slots. Task này
            # vẫn phải bị ép về đúng đầu cụm FixedLesson, thay vì được solver
            # coi là một cụm thường và chọn đầu khác.
            item = pop_matching_fixed_task(pending, fixed_slot, fixed_size)
            if item is None:
                invalid_fixed_assignment_ids.add(assignment.id)
                break
            task_rows.append(
                (
                    assignment,
                    task_index,
                    fixed_size,
                    assignment_requires_double(assignment),
                    fixed_slot,
                    tuple(item["anchor_slots"]),
                    (fixed_slot,),
                )
            )
            task_index += 1
        if assignment.id in invalid_fixed_assignment_ids:
            continue
        for item in pending:
            task_rows.append(
                (
                    assignment,
                    task_index,
                    item["size"],
                    assignment_requires_double(assignment),
                    None,
                    tuple(item["anchor_slots"]),
                    item["candidate_starts"],
                )
            )
            task_index += 1

    if invalid_assignment_ids or invalid_fixed_assignment_ids:
        affected_ids = set(invalid_assignment_ids).union(invalid_fixed_assignment_ids)
        missing = sum(
            max(0, assignment.periods_per_week - len(existing_slots[assignment.id]))
            for assignment in assignments
            if assignment.id in affected_ids
        )
        if affected_ids and missing == 0:
            # Không được trả unscheduled=0 khi chính dữ liệu hiện tại đã làm
            # pattern_completion_plan() thất bại (ví dụ dữ liệu cũ bị thừa tiết).
            missing = len(affected_ids)
        return {
            "lessons": [],
            "unscheduled": missing,
            "score": missing * 10000,
            "invalid_assignments": invalid_assignment_ids,
            "invalid_fixed_assignments": sorted(invalid_fixed_assignment_ids),
        }

    if not task_rows:
        return {"lessons": [], "unscheduled": 0, "score": 0}

    def cp_sat_primary():
        """Solve the prepared scheduling tasks with OR-Tools CP-SAT.

        Hard constraints stay authoritative here.  If OR-Tools is not installed,
        no feasible solution is found within the bounded search time, or the
        model is infeasible, the caller falls back to the legacy GA solver.
        """
        try:
            from ortools.sat.python import cp_model
        except ImportError:
            logger.warning("OR-Tools is not installed; falling back to GA scheduler")
            return None

        model = cp_model.CpModel()
        teacher_unavailable = {
            teacher_id: parse_slots(teacher.unavailable_json)
            for teacher_id, teacher in teachers.items()
        }
        class_unavailable = {
            class_id: parse_slots(row.unavailable_json)
            for class_id, row in classes.items()
        }

        existing_teacher_slot = defaultdict(int)
        existing_class_slot = defaultdict(int)
        existing_teacher_day = Counter()
        existing_class_subject_day = Counter()
        existing_assignment_slots = defaultdict(set)
        for lesson in existing:
            assignment = next(
                (row for row in assignments if row.id == lesson.assignment_id), None
            )
            if not assignment:
                continue
            day = lesson.slot // ppd
            existing_teacher_slot[(assignment.teacher_id, lesson.slot)] += 1
            existing_class_slot[(assignment.class_id, lesson.slot)] += 1
            existing_teacher_day[(assignment.teacher_id, day)] += 1
            existing_class_subject_day[
                (assignment.class_id, assignment.subject_id, day)
            ] += 1
            existing_assignment_slots[assignment.id].add(lesson.slot)

        task_options = []
        option_vars = []
        slot_var_by_teacher = defaultdict(list)
        slot_var_by_class = defaultdict(list)
        day_var_by_teacher = defaultdict(list)
        day_var_by_class_subject = defaultdict(list)
        assignment_slot_vars = defaultdict(list)
        objective_terms = []

        for index, task in enumerate(task_rows):
            (
                assignment,
                group_index,
                size,
                explicit,
                forced,
                anchor_slots,
                planned_starts,
            ) = task
            anchor = set(anchor_slots)
            missing_size = size - len(anchor)
            if forced is not None:
                candidate_pool = [forced]
            elif planned_starts is not None:
                candidate_pool = list(planned_starts)
            else:
                candidate_pool = [
                    slot
                    for slot in slots
                    if (slot % ppd) % p.periods_per_session + size
                    <= p.periods_per_session
                ]

            rows = []
            for slot in sorted(set(candidate_pool)):
                if slot not in slots:
                    continue
                day = slot // ppd
                position = slot % ppd
                session = position // p.periods_per_session
                period = position % p.periods_per_session
                if period + size > p.periods_per_session:
                    continue
                group_slots = tuple(range(slot, slot + size))
                group_set = set(group_slots)
                if anchor and not anchor.issubset(group_set):
                    continue
                new_slots = tuple(
                    candidate for candidate in group_slots if candidate not in anchor
                )
                if len(new_slots) != missing_size:
                    continue
                if any(
                    candidate // ppd != day
                    or (candidate % ppd) // p.periods_per_session != session
                    for candidate in group_slots
                ):
                    continue
                if any(
                    candidate in global_blocked
                    or candidate in teacher_unavailable[assignment.teacher_id]
                    or candidate in class_unavailable[assignment.class_id]
                    for candidate in new_slots
                ):
                    continue
                if any(
                    existing_teacher_slot[(assignment.teacher_id, candidate)]
                    or existing_class_slot[(assignment.class_id, candidate)]
                    for candidate in new_slots
                ):
                    continue
                if (
                    existing_teacher_day[(assignment.teacher_id, day)] + missing_size
                    > teachers[assignment.teacher_id].max_periods_day
                ):
                    continue
                var = model.NewBoolVar(f"task_{index}_start_{slot}")
                row = (slot, new_slots, group_slots, day, var)
                rows.append(row)
                for candidate in new_slots:
                    slot_var_by_teacher[(assignment.teacher_id, candidate)].append(var)
                    slot_var_by_class[(assignment.class_id, candidate)].append(var)
                day_var_by_teacher[(assignment.teacher_id, day)].append(
                    (var, missing_size)
                )
                day_var_by_class_subject[
                    (assignment.class_id, assignment.subject_id, day)
                ].append((var, missing_size))
                for candidate in new_slots:
                    assignment_slot_vars[(assignment.id, candidate)].append(var)
                # A small deterministic preference for earlier periods.  Main
                # distribution penalties are modeled below.
                objective_terms.append((period + 1) * var)
            if not rows:
                return None
            model.Add(sum(row[4] for row in rows) == 1)
            task_options.append(rows)
            option_vars.extend(row[4] for row in rows)

        # Teacher/class collisions for every concrete timetable slot.
        for (teacher_id, slot), vars_for_slot in slot_var_by_teacher.items():
            model.Add(
                sum(vars_for_slot) + existing_teacher_slot[(teacher_id, slot)] <= 1
            )
        for (class_id, slot), vars_for_slot in slot_var_by_class.items():
            model.Add(sum(vars_for_slot) + existing_class_slot[(class_id, slot)] <= 1)

        # Teacher daily workload.
        for (teacher_id, day), weighted in day_var_by_teacher.items():
            model.Add(
                sum(var * weight for var, weight in weighted)
                + existing_teacher_day[(teacher_id, day)]
                <= teachers[teacher_id].max_periods_day
            )

        # Subject max-consecutive constraint, checked with sliding windows inside
        # each class/day/session.
        occupancy_by_class_subject_slot = defaultdict(list)
        for index, rows in enumerate(task_options):
            assignment = task_rows[index][0]
            for _start, new_slots, _group_slots, _day, var in rows:
                for candidate in new_slots:
                    occupancy_by_class_subject_slot[
                        (assignment.class_id, assignment.subject_id, candidate)
                    ].append(var)
        existing_css = defaultdict(int)
        for lesson in existing:
            assignment = next(
                (row for row in assignments if row.id == lesson.assignment_id), None
            )
            if assignment:
                existing_css[
                    (assignment.class_id, assignment.subject_id, lesson.slot)
                ] += 1
        for assignment in assignments:
            subject = subjects.get(assignment.subject_id)
            if not subject:
                continue
            max_run = max(1, int(subject.max_consecutive or 1))
            window = max_run + 1
            if window > p.periods_per_session:
                continue
            for day in range(p.days):
                for session in range(p.sessions):
                    base = day * ppd + session * p.periods_per_session
                    for start_period in range(p.periods_per_session - window + 1):
                        window_slots = [
                            base + start_period + offset for offset in range(window)
                        ]
                        expr = []
                        fixed_count = 0
                        for candidate in window_slots:
                            expr.extend(
                                occupancy_by_class_subject_slot[
                                    (
                                        assignment.class_id,
                                        assignment.subject_id,
                                        candidate,
                                    )
                                ]
                            )
                            fixed_count += existing_css[
                                (assignment.class_id, assignment.subject_id, candidate)
                            ]
                        if expr or fixed_count:
                            model.Add(sum(expr) + fixed_count <= max_run)

        # Soft objective for preferred_double: chỉ thưởng một cụm ĐÚNG 2 tiết
        # liên tiếp trong cùng ngày/buổi. Cụm 3 hoặc 4 tiết không được tách ngầm
        # thành các "cặp" ảo; nhờ vậy solver và giao diện có cùng một định nghĩa
        # về tiết đôi. Đây vẫn chỉ là mục tiêu mềm, không biến preferred_double
        # thành ràng buộc bắt buộc.
        for assignment in assignments:
            if not assignment_prefers_double(assignment):
                continue
            for day in range(p.days):
                for session in range(p.sessions):
                    base = day * ppd + session * p.periods_per_session
                    for period in range(p.periods_per_session - 1):
                        left = base + period
                        right = left + 1
                        left_vars = assignment_slot_vars[(assignment.id, left)]
                        right_vars = assignment_slot_vars[(assignment.id, right)]
                        left_fixed = (
                            1 if left in existing_assignment_slots[assignment.id] else 0
                        )
                        right_fixed = (
                            1
                            if right in existing_assignment_slots[assignment.id]
                            else 0
                        )
                        if not (left_fixed or left_vars) or not (
                            right_fixed or right_vars
                        ):
                            continue

                        previous = left - 1 if period > 0 else None
                        following = (
                            right + 1 if period + 2 < p.periods_per_session else None
                        )
                        previous_vars = (
                            assignment_slot_vars[(assignment.id, previous)]
                            if previous is not None
                            else []
                        )
                        following_vars = (
                            assignment_slot_vars[(assignment.id, following)]
                            if following is not None
                            else []
                        )
                        previous_fixed = (
                            1
                            if previous is not None
                            and previous in existing_assignment_slots[assignment.id]
                            else 0
                        )
                        following_fixed = (
                            1
                            if following is not None
                            and following in existing_assignment_slots[assignment.id]
                            else 0
                        )

                        pair = model.NewBoolVar(
                            f"preferred_pair_{assignment.id}_{left}_{right}"
                        )
                        left_occupancy = sum(left_vars) + left_fixed
                        right_occupancy = sum(right_vars) + right_fixed
                        previous_occupancy = sum(previous_vars) + previous_fixed
                        following_occupancy = sum(following_vars) + following_fixed
                        model.Add(pair <= left_occupancy)
                        model.Add(pair <= right_occupancy)
                        model.Add(pair <= 1 - previous_occupancy)
                        model.Add(pair <= 1 - following_occupancy)
                        objective_terms.append(-14 * pair)

        # Soft objective: spread the same class/subject across days.  Penalize
        # every period beyond the first one on a day.  For preferred_double, the
        # 14-point adjacency reward above outweighs this 8-point spread penalty,
        # so a feasible double period is preferred while separated periods remain
        # allowed when other constraints require them.
        for (class_id, subject_id, day), weighted in day_var_by_class_subject.items():
            existing_count = existing_class_subject_day[(class_id, subject_id, day)]
            total = sum(var * weight for var, weight in weighted) + existing_count
            overflow = model.NewIntVar(
                0,
                p.periods_per_session * p.sessions,
                f"spread_{class_id}_{subject_id}_{day}",
            )
            model.Add(overflow >= total - 1)
            model.Add(overflow >= 0)
            objective_terms.append(8 * overflow)

        model.Minimize(sum(objective_terms))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(3.0, min(20.0, float(tries) / 12.0))
        solver.parameters.num_search_workers = max(1, min(8, os.cpu_count() or 1))
        solver.parameters.random_seed = 42
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            logger.info(
                "CP-SAT did not produce a feasible timetable (status=%s); using GA fallback",
                status,
            )
            return None

        lessons = []
        final_slots = defaultdict(set)
        for lesson in existing:
            final_slots[lesson.assignment_id].add(lesson.slot)
        for index, rows in enumerate(task_options):
            assignment = task_rows[index][0]
            forced = task_rows[index][4]
            for _start, new_slots, _group_slots, _day, var in rows:
                if solver.Value(var):
                    for candidate in new_slots:
                        lessons.append((assignment.id, candidate, forced is not None))
                        final_slots[assignment.id].add(candidate)
                    break

        soft_score = 0.0
        for assignment in assignments:
            slots_for_assignment = final_slots[assignment.id]
            if assignment_prefers_double(assignment):
                formed_pairs = preferred_double_pair_count(p, slots_for_assignment)
                soft_score += (
                    max(0, assignment.periods_per_week // 2 - formed_pairs) * 14
                )
            day_counts = Counter(slot // ppd for slot in slots_for_assignment)
            soft_score += sum(max(0, count - 1) * 8 for count in day_counts.values())
        return {
            "lessons": lessons,
            "unscheduled": 0,
            "score": round(soft_score, 2),
            "solver": "cp_sat",
            "optimal": status == cp_model.OPTIMAL,
            "wall_time": round(solver.WallTime(), 3),
        }

    cp_result = cp_sat_primary()
    if cp_result is not None:
        return cp_result

    random.shuffle(task_rows)
    task_rows.sort(
        key=lambda task: (
            1 if task[4] is not None else 0,
            task[2] - len(task[5]),
            len(parse_slots(teachers[task[0].teacher_id].unavailable_json))
            + len(parse_slots(classes[task[0].class_id].unavailable_json)),
            -existing_counts[task[0].id],
        ),
        reverse=True,
    )

    def valid_start_slots(size: int):
        return [
            slot
            for slot in slots
            if (slot % ppd) % p.periods_per_session + size <= p.periods_per_session
        ]

    starts_by_size = {}

    def start_pool(size: int):
        pool = starts_by_size.get(size)
        if pool is None:
            pool = valid_start_slots(size)
            starts_by_size[size] = pool
        return pool

    def evaluate(genes: list[int | None]):
        teacher_busy = defaultdict(set)
        class_busy = defaultdict(set)
        assignment_busy = defaultdict(set)
        teacher_day = Counter()
        class_sub_day = Counter()
        class_sub_slots = defaultdict(set)
        placed = []
        chosen_starts = [None] * len(task_rows)
        unscheduled = 0
        gene_miss = 0.0

        for lesson in existing:
            assignment = next(
                (x for x in assignments if x.id == lesson.assignment_id), None
            )
            if not assignment:
                continue
            day = lesson.slot // ppd
            teacher_busy[assignment.teacher_id].add(lesson.slot)
            class_busy[assignment.class_id].add(lesson.slot)
            assignment_busy[assignment.id].add(lesson.slot)
            teacher_day[(assignment.teacher_id, day)] += 1
            class_sub_day[(assignment.class_id, assignment.subject_id, day)] += 1
            class_sub_slots[(assignment.class_id, assignment.subject_id, day)].add(
                lesson.slot % ppd
            )

        for index, task in enumerate(task_rows):
            (
                assignment,
                group_index,
                size,
                explicit,
                forced,
                anchor_slots,
                planned_starts,
            ) = task
            anchor = set(anchor_slots)
            missing_size = size - len(anchor)
            gene = forced if forced is not None else genes[index]
            if forced is not None:
                candidate_pool = [forced]
            elif planned_starts is not None:
                candidate_pool = list(planned_starts)
            else:
                candidate_pool = start_pool(size)
            tu = parse_slots(teachers[assignment.teacher_id].unavailable_json)
            cu = parse_slots(classes[assignment.class_id].unavailable_json)
            best_slot = None
            best_score = None
            for slot in candidate_pool:
                if slot is None or slot not in slots:
                    continue
                day = slot // ppd
                position = slot % ppd
                session = position // p.periods_per_session
                period = position % p.periods_per_session
                if period + size > p.periods_per_session:
                    continue
                group_slots = list(range(slot, slot + size))
                group_set = set(group_slots)
                if anchor and not anchor.issubset(group_set):
                    continue
                new_slots = [
                    candidate for candidate in group_slots if candidate not in anchor
                ]
                if len(new_slots) != missing_size:
                    continue
                if any(
                    candidate // ppd != day
                    or (candidate % ppd) // p.periods_per_session != session
                    for candidate in group_slots
                ):
                    continue
                if any(
                    candidate in global_blocked
                    or candidate in tu
                    or candidate in cu
                    or candidate in teacher_busy[assignment.teacher_id]
                    or candidate in class_busy[assignment.class_id]
                    for candidate in new_slots
                ):
                    continue
                if (
                    teacher_day[(assignment.teacher_id, day)] + missing_size
                    > teachers[assignment.teacher_id].max_periods_day
                ):
                    continue
                existing_periods = [
                    candidate % p.periods_per_session
                    for candidate in class_sub_slots[
                        (assignment.class_id, assignment.subject_id, day)
                    ]
                    if candidate // p.periods_per_session == session
                ]
                run = sorted(set(existing_periods + list(range(period, period + size))))
                longest = current = 1
                for left, right in zip(run, run[1:]):
                    current = current + 1 if right == left + 1 else 1
                    longest = max(longest, current)
                if longest > subjects[assignment.subject_id].max_consecutive:
                    continue
                score = class_sub_day[
                    (assignment.class_id, assignment.subject_id, day)
                ] * 8 + sum(
                    (candidate % p.periods_per_session) * 0.15
                    for candidate in new_slots
                )
                neighbors = []
                if period > 0:
                    neighbors.append(slot - 1)
                if period + size < p.periods_per_session:
                    neighbors.append(slot + size)
                for neighbor in neighbors:
                    if neighbor in teacher_busy[assignment.teacher_id]:
                        score -= 1.2
                    if (
                        assignment_prefers_double(assignment)
                        and neighbor in assignment_busy[assignment.id]
                    ):
                        score -= 7.0
                if gene is not None:
                    if slot == gene:
                        score -= 8
                    else:
                        score += abs(slot - gene) * 0.05
                if best_score is None or score < best_score:
                    best_score = score
                    best_slot = slot
            if best_slot is None:
                unscheduled += missing_size
                continue
            chosen_starts[index] = best_slot
            day = best_slot // ppd
            gene_value = forced if forced is not None else genes[index]
            if gene_value is not None and best_slot != gene_value:
                gene_miss += abs(best_slot - gene_value)
            for slot in range(best_slot, best_slot + size):
                if slot in anchor:
                    continue
                teacher_busy[assignment.teacher_id].add(slot)
                class_busy[assignment.class_id].add(slot)
                assignment_busy[assignment.id].add(slot)
                class_sub_slots[(assignment.class_id, assignment.subject_id, day)].add(
                    slot % ppd
                )
                placed.append((assignment.id, slot, forced is not None))
            teacher_day[(assignment.teacher_id, day)] += missing_size
            class_sub_day[(assignment.class_id, assignment.subject_id, day)] += (
                missing_size
            )

        score = unscheduled * 10000 + gene_miss * 0.05
        for (cid, sid, day), n in class_sub_day.items():
            score += max(0, n - 1) * 10
        for tid, busy in teacher_busy.items():
            for day in range(p.days):
                xs = sorted(slot % ppd for slot in busy if slot // ppd == day)
                if xs:
                    score += (xs[-1] - xs[0] + 1 - len(xs)) * 2
        for assignment in assignments:
            if not assignment_prefers_double(assignment):
                continue
            formed_pairs = preferred_double_pair_count(
                p, assignment_busy[assignment.id]
            )
            target_pairs = assignment.periods_per_week // 2
            score += max(0, target_pairs - formed_pairs) * 14
        return {
            "lessons": placed,
            "unscheduled": unscheduled,
            "score": round(score, 2),
            "genes": chosen_starts,
        }

    def genes_from_candidate(candidate):
        genes = list(candidate.get("genes", []))
        if len(genes) != len(task_rows):
            genes = [None] * len(task_rows)
        return genes

    def random_gene(task):
        (
            assignment,
            group_index,
            size,
            explicit,
            forced,
            anchor_slots,
            planned_starts,
        ) = task
        if forced is not None:
            return forced
        pool = list(planned_starts) if planned_starts is not None else start_pool(size)
        return random.choice(pool) if pool else None

    def mutate(genes):
        child = genes[:]
        for index, task in enumerate(task_rows):
            (
                assignment,
                group_index,
                size,
                explicit,
                forced,
                anchor_slots,
                planned_starts,
            ) = task
            if forced is not None:
                child[index] = forced
                continue
            if random.random() < 0.15:
                child[index] = random_gene(task) if random.random() < 0.9 else None
        return child

    def crossover(left, right):
        child = []
        for index, task in enumerate(task_rows):
            (
                assignment,
                group_index,
                size,
                explicit,
                forced,
                anchor_slots,
                planned_starts,
            ) = task
            if forced is not None:
                child.append(forced)
            elif random.random() < 0.5:
                child.append(left[index])
            else:
                child.append(right[index])
        return child

    def exact_fallback(node_limit: int):
        """Thử tìm lời giải đầy đủ bằng backtracking cho bài toán vừa/nhỏ.

        GA vẫn được dùng trước để có tốc độ tốt. Khi GA bỏ sót lời giải, bước
        này duyệt có hệ thống và có thể chứng minh vô nghiệm nếu hoàn tất toàn
        bộ cây tìm kiếm trước giới hạn nút.
        """
        teacher_busy = defaultdict(set)
        class_busy = defaultdict(set)
        assignment_busy = defaultdict(set)
        teacher_day = Counter()
        class_sub_day = Counter()
        class_sub_slots = defaultdict(set)
        for lesson in existing:
            assignment = next(
                (x for x in assignments if x.id == lesson.assignment_id), None
            )
            if not assignment:
                continue
            day = lesson.slot // ppd
            teacher_busy[assignment.teacher_id].add(lesson.slot)
            class_busy[assignment.class_id].add(lesson.slot)
            assignment_busy[assignment.id].add(lesson.slot)
            teacher_day[(assignment.teacher_id, day)] += 1
            class_sub_day[(assignment.class_id, assignment.subject_id, day)] += 1
            class_sub_slots[(assignment.class_id, assignment.subject_id, day)].add(
                lesson.slot % ppd
            )

        raw_candidates = []
        for task in task_rows:
            (
                assignment,
                group_index,
                size,
                explicit,
                forced,
                anchor_slots,
                planned_starts,
            ) = task
            if forced is not None:
                pool = [forced]
            elif planned_starts is not None:
                pool = list(planned_starts)
            else:
                pool = start_pool(size)
            raw_candidates.append([slot for slot in pool if slot is not None])

        placed_by_task = {}
        remaining = set(range(len(task_rows)))
        nodes = 0
        limit_hit = False

        def options_for(index: int):
            (
                assignment,
                group_index,
                size,
                explicit,
                forced,
                anchor_slots,
                planned_starts,
            ) = task_rows[index]
            anchor = set(anchor_slots)
            missing_size = size - len(anchor)
            tu = parse_slots(teachers[assignment.teacher_id].unavailable_json)
            cu = parse_slots(classes[assignment.class_id].unavailable_json)
            options = []
            for slot in raw_candidates[index]:
                if slot not in slots:
                    continue
                day = slot // ppd
                position = slot % ppd
                session = position // p.periods_per_session
                period = position % p.periods_per_session
                if period + size > p.periods_per_session:
                    continue
                group_slots = tuple(range(slot, slot + size))
                group_set = set(group_slots)
                if anchor and not anchor.issubset(group_set):
                    continue
                new_slots = tuple(
                    candidate for candidate in group_slots if candidate not in anchor
                )
                if len(new_slots) != missing_size:
                    continue
                if any(
                    candidate // ppd != day
                    or (candidate % ppd) // p.periods_per_session != session
                    for candidate in group_slots
                ):
                    continue
                if any(
                    candidate in global_blocked
                    or candidate in tu
                    or candidate in cu
                    or candidate in teacher_busy[assignment.teacher_id]
                    or candidate in class_busy[assignment.class_id]
                    for candidate in new_slots
                ):
                    continue
                if (
                    teacher_day[(assignment.teacher_id, day)] + missing_size
                    > teachers[assignment.teacher_id].max_periods_day
                ):
                    continue
                existing_periods = [
                    candidate % p.periods_per_session
                    for candidate in class_sub_slots[
                        (assignment.class_id, assignment.subject_id, day)
                    ]
                    if candidate // p.periods_per_session == session
                ]
                run = sorted(set(existing_periods + list(range(period, period + size))))
                longest = current = 1
                for left, right in zip(run, run[1:]):
                    current = current + 1 if right == left + 1 else 1
                    longest = max(longest, current)
                if longest > subjects[assignment.subject_id].max_consecutive:
                    continue
                adjacent_same = 0
                if assignment_prefers_double(assignment):
                    if period > 0 and slot - 1 in assignment_busy[assignment.id]:
                        adjacent_same += 1
                    if (
                        period + size < p.periods_per_session
                        and slot + size in assignment_busy[assignment.id]
                    ):
                        adjacent_same += 1
                score = (
                    class_sub_day[(assignment.class_id, assignment.subject_id, day)] * 8
                    + sum(
                        (candidate % p.periods_per_session) * 0.15
                        for candidate in new_slots
                    )
                    - adjacent_same * 7
                )
                options.append((score, slot, group_slots, new_slots, day))
            options.sort(key=lambda item: (item[0], item[1]))
            return options

        def apply(index: int, option):
            _score, slot, group_slots, new_slots, day = option
            (
                assignment,
                group_index,
                size,
                explicit,
                forced,
                anchor_slots,
                planned_starts,
            ) = task_rows[index]
            for candidate in new_slots:
                teacher_busy[assignment.teacher_id].add(candidate)
                class_busy[assignment.class_id].add(candidate)
                assignment_busy[assignment.id].add(candidate)
                class_sub_slots[(assignment.class_id, assignment.subject_id, day)].add(
                    candidate % ppd
                )
            teacher_day[(assignment.teacher_id, day)] += len(new_slots)
            class_sub_day[(assignment.class_id, assignment.subject_id, day)] += len(
                new_slots
            )
            placed_by_task[index] = (
                assignment.id,
                tuple(new_slots),
                forced is not None,
            )

        def undo(index: int, option):
            _score, slot, group_slots, new_slots, day = option
            (
                assignment,
                group_index,
                size,
                explicit,
                forced,
                anchor_slots,
                planned_starts,
            ) = task_rows[index]
            placed_by_task.pop(index, None)
            teacher_day[(assignment.teacher_id, day)] -= len(new_slots)
            class_sub_day[(assignment.class_id, assignment.subject_id, day)] -= len(
                new_slots
            )
            for candidate in new_slots:
                teacher_busy[assignment.teacher_id].remove(candidate)
                class_busy[assignment.class_id].remove(candidate)
                assignment_busy[assignment.id].remove(candidate)
                class_sub_slots[
                    (assignment.class_id, assignment.subject_id, day)
                ].remove(candidate % ppd)

        def search():
            nonlocal nodes, limit_hit
            if not remaining:
                return True
            nodes += 1
            if nodes > node_limit:
                limit_hit = True
                return False
            selected_index = None
            selected_options = None
            for index in tuple(remaining):
                options = options_for(index)
                if not options:
                    return False
                if selected_options is None or len(options) < len(selected_options):
                    selected_index = index
                    selected_options = options
                    if len(options) == 1:
                        break
            remaining.remove(selected_index)
            for option in selected_options:
                apply(selected_index, option)
                if search():
                    return True
                undo(selected_index, option)
                if limit_hit:
                    break
            remaining.add(selected_index)
            return False

        solved = search()
        if not solved:
            return None, not limit_hit, nodes
        lessons = []
        for index in range(len(task_rows)):
            assignment_id, new_slots, locked = placed_by_task[index]
            lessons.extend((assignment_id, slot, locked) for slot in new_slots)
        soft_score = 0.0
        final_slots = defaultdict(set)
        for lesson in existing:
            final_slots[lesson.assignment_id].add(lesson.slot)
        for assignment_id, slot, _locked in lessons:
            final_slots[assignment_id].add(slot)
        for assignment in assignments:
            if assignment_prefers_double(assignment):
                formed_pairs = preferred_double_pair_count(
                    p, final_slots[assignment.id]
                )
                soft_score += (
                    max(0, assignment.periods_per_week // 2 - formed_pairs) * 14
                )
        return (
            {
                "lessons": lessons,
                "unscheduled": 0,
                "score": round(soft_score, 2),
                "exact": True,
            },
            True,
            nodes,
        )

    # Quy mô cũ dừng ở 40×60 nên các project vừa/lớn dễ hết lượt trước khi
    # tìm thấy nghiệm. Vẫn giữ trần hữu hạn để request không chạy vô hạn.
    population_size = max(24, min(56, max(18, len(task_rows))))
    generations = max(18, min(75, max(tries // 3, 24)))
    elite_count = max(2, population_size // 5)

    def candidate_key(candidate):
        # Ràng buộc cứng: lịch thiếu ít tiết hơn luôn tốt hơn, bất kể điểm mềm.
        return (candidate["unscheduled"], candidate["score"])

    seed_candidate = evaluate([None] * len(task_rows))
    best_candidate = seed_candidate
    population = [genes_from_candidate(seed_candidate)]
    for _ in range(population_size - 1):
        population.append([random_gene(task) for task in task_rows])

    evaluated = []
    for genes in population:
        candidate = evaluate(genes)
        evaluated.append((candidate, genes))
        if candidate_key(candidate) < candidate_key(best_candidate):
            best_candidate = candidate

    for _ in range(generations):
        evaluated.sort(key=lambda item: candidate_key(item[0]))
        elites = [genes for _candidate, genes in evaluated[:elite_count]]
        if candidate_key(evaluated[0][0]) < candidate_key(best_candidate):
            best_candidate = evaluated[0][0]
        next_population = elites[:]
        while len(next_population) < population_size:
            pool = evaluated[: max(6, population_size // 2)]
            parent1 = random.choice(pool)[1]
            parent2 = random.choice(pool)[1]
            child = mutate(crossover(parent1, parent2))
            next_population.append(child)
        evaluated = []
        for genes in next_population:
            candidate = evaluate(genes)
            evaluated.append((candidate, genes))
            if candidate_key(candidate) < candidate_key(best_candidate):
                best_candidate = candidate

    if evaluated:
        evaluated.sort(key=lambda item: candidate_key(item[0]))
        if candidate_key(evaluated[0][0]) < candidate_key(best_candidate):
            best_candidate = evaluated[0][0]

    if best_candidate["unscheduled"] > 0:
        missing_periods = sum(task[2] - len(task[5]) for task in task_rows)
        exact_allowed = len(task_rows) <= 48 and missing_periods <= 60
        if exact_allowed:
            node_limit = min(750000, max(75000, tries * 2000))
            exact_result, exhausted, nodes = exact_fallback(node_limit)
            if exact_result is not None:
                return exact_result
            best_candidate["proven_infeasible"] = exhausted
            best_candidate["search_limited"] = not exhausted
            best_candidate["exact_nodes"] = nodes
        else:
            best_candidate["proven_infeasible"] = False
            best_candidate["search_limited"] = True
    return best_candidate


def solve_missing(
    db: Session, p: Project, tries=120, target_assignment_ids: Optional[set[int]] = None
):
    """Giữ nguyên lịch hiện có và chỉ xếp phần còn thiếu của các phân công đích."""
    return ga_schedule(
        db,
        p,
        mode="missing",
        tries=tries,
        target_assignment_ids=target_assignment_ids,
    )


def solve_rebuild(db: Session, p: Project, tries=220):
    """Giữ tiết cố định, xếp lại toàn bộ phần còn lại."""
    return ga_schedule(db, p, mode="rebuild", tries=tries)


def solve(db: Session, p: Project, tries=80):
    return ga_schedule(db, p, mode="full", tries=tries)


def seed_project(db: Session, p: Project):
    d1 = Department(project_id=p.id, name="Tổ Toán - Tin")
    d2 = Department(project_id=p.id, name="Tổ Ngữ văn")
    db.add_all([d1, d2])
    db.flush()
    s1 = Subject(project_id=p.id, name="Toán", short_name="TOÁN", max_consecutive=2)
    s2 = Subject(project_id=p.id, name="Ngữ văn", short_name="VĂN", max_consecutive=2)
    s3 = Subject(project_id=p.id, name="Tin học", short_name="TIN", max_consecutive=1)
    db.add_all([s1, s2, s3])
    db.flush()
    t1 = Teacher(
        project_id=p.id,
        department_id=d1.id,
        name="Nguyễn Văn An",
        short_name="An",
        max_periods_day=4,
    )
    t2 = Teacher(
        project_id=p.id,
        department_id=d2.id,
        name="Trần Thị Bình",
        short_name="Bình",
        max_periods_day=4,
    )
    t3 = Teacher(
        project_id=p.id,
        department_id=d1.id,
        name="Lê Minh Châu",
        short_name="Châu",
        max_periods_day=4,
    )
    db.add_all([t1, t2, t3])
    db.flush()
    db.add_all(
        [
            TeacherSubject(project_id=p.id, teacher_id=t1.id, subject_id=s1.id),
            TeacherSubject(project_id=p.id, teacher_id=t2.id, subject_id=s2.id),
            TeacherSubject(project_id=p.id, teacher_id=t3.id, subject_id=s3.id),
        ]
    )
    g = Grade(project_id=p.id, name="Khối 10")
    db.add(g)
    db.flush()
    c1 = SchoolClass(project_id=p.id, grade_id=g.id, name="10A1")
    c2 = SchoolClass(project_id=p.id, grade_id=g.id, name="10A2")
    db.add_all([c1, c2])
    db.flush()
    for c in [c1, c2]:
        db.add_all(
            [
                Assignment(
                    project_id=p.id,
                    class_id=c.id,
                    subject_id=s1.id,
                    teacher_id=t1.id,
                    periods_per_week=4,
                ),
                Assignment(
                    project_id=p.id,
                    class_id=c.id,
                    subject_id=s2.id,
                    teacher_id=t2.id,
                    periods_per_week=3,
                ),
                Assignment(
                    project_id=p.id,
                    class_id=c.id,
                    subject_id=s3.id,
                    teacher_id=t3.id,
                    periods_per_week=2,
                ),
            ]
        )
    db.commit()


def ensure_demo():
    db = SessionLocal()
    try:
        existing_super_admin = db.scalar(
            select(User)
            .where(User.role == "super_admin")
            .order_by(User.id.asc())
            .limit(1)
        )
        configured_target = (
            db.get(User, SUPER_ADMIN_USER_ID) if SUPER_ADMIN_USER_ID > 0 else None
        )
        if SUPER_ADMIN_USER_ID > 0 and configured_target is None:
            logger.error(
                "SUPER_ADMIN_USER_ID=%s không tồn tại; không hạ quyền super_admin hiện tại.",
                SUPER_ADMIN_USER_ID,
            )
            if existing_super_admin is not None:
                return

        email_target = (
            db.scalar(
                select(User)
                .where(func.lower(User.email) == BOOTSTRAP_ADMIN_EMAIL)
                .limit(1)
            )
            if BOOTSTRAP_ADMIN_EMAIL
            else None
        )
        target = (
            configured_target
            if configured_target is not None
            else (existing_super_admin or email_target)
        )

        if target is not None and target.role == "super_admin":
            changed = not bool(target.is_superadmin)
            target.is_superadmin = True
            for other in db.scalars(
                select(User).where(User.role == "super_admin", User.id != target.id)
            ).all():
                other.role = "admin"
                other.is_superadmin = False
                changed = True
            if changed:
                db.commit()
            return

        if target is None and (
            not BOOTSTRAP_ADMIN_EMAIL or len(BOOTSTRAP_ADMIN_PASSWORD) < 8
        ):
            if existing_super_admin is not None:
                return
            raise RuntimeError(
                "Database chưa có super admin. Hãy cấu hình SUPER_ADMIN_USER_ID trỏ tới "
                "một tài khoản tồn tại hoặc cấu hình BOOTSTRAP_ADMIN_EMAIL và "
                "BOOTSTRAP_ADMIN_PASSWORD (ít nhất 8 ký tự) để khôi phục quyền quản trị."
            )

        user = target
        if user is None:
            user = User(
                email=BOOTSTRAP_ADMIN_EMAIL,
                name="Quản trị viên",
                password_hash=pwd.hash(BOOTSTRAP_ADMIN_PASSWORD),
                role="super_admin",
                is_superadmin=True,
            )
            db.add(user)
            db.flush()
        else:
            user.role = "super_admin"
            user.is_superadmin = True
            if BOOTSTRAP_ADMIN_EMAIL and len(BOOTSTRAP_ADMIN_PASSWORD) >= 8:
                user.password_hash = pwd.hash(BOOTSTRAP_ADMIN_PASSWORD)
                user.session_version = max(1, user.session_version or 1) + 1
            if not (user.name or "").strip():
                user.name = "Quản trị viên"

        # Chỉ hạ các super_admin khác sau khi tài khoản đích đã tồn tại trong
        # transaction hiện tại. Nhờ vậy cấu hình sai không thể làm mất quyền.
        for other in db.scalars(
            select(User).where(User.role == "super_admin", User.id != user.id)
        ).all():
            other.role = "admin"
            other.is_superadmin = False

        db.commit()
        if SEED_DEMO_DATA and db.scalar(select(Project.id).limit(1)) is None:
            school = ensure_school_for_name(db, "THPT Demo")
            p = Project(
                owner_id=user.id,
                school_id=school.id,
                name="TKB học kỳ I",
                school_name=school.name,
                days=6,
                sessions=2,
                periods_per_session=5,
            )
            db.add(p)
            db.commit()
            seed_project(db, p)
    finally:
        db.close()


def initialize_database():
    initialize_schema()
    ensure_demo()


run_database_bootstrap_step(initialize_database)
