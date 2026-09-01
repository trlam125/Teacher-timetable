from __future__ import annotations

import io
import json
import logging
import random
import secrets
import smtplib
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Optional

from app.logic import (
    clear_teacher_identity,
    fixed_group_validation_error,
    normalize_slot_values,
    parse_integer_set,
    pop_matching_fixed_task,
    remap_slot_for_session_expansion,
    remap_slots_for_session_expansion,
    required_double_removal_slots,
    revoke_last_teacher_profile,
    schedule_validation_peers,
)
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
import hashlib
import hmac
import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, delete, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

load_dotenv()

logger = logging.getLogger("smart_tkb")

ADMIN_ROLES = frozenset({"admin", "super_admin"})
MAX_CHATBOT_ERROR_LOGS = 500
MAX_CHATBOT_DOCUMENT_CONTEXT_CHARS = 350_000
MAX_SCHEDULE_AUDIT_FILE_BYTES = 15 * 1024 * 1024

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
    raise RuntimeError(
        "Thiếu SECRET_KEY. Hãy tạo khóa bí mật và thêm vào file .env."
    )

# Chuẩn hóa về driver psycopg 3.
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://", "postgresql+psycopg://", 1
    )

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120), default="Giáo viên")
    role: Mapped[str] = mapped_column(String(20), default="pending")
    requested_teacher_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    requested_project_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    teacher_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    reset_token_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reset_token_expires_at: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False)
    session_version: Mapped[int] = mapped_column(Integer, default=1)

class RegistrationVerification(Base):
    __tablename__ = "registration_verifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), unique=True, index=True)
    otp_hash: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[str] = mapped_column(String(40))
    resend_available_at: Mapped[str] = mapped_column(String(40))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(40), default=lambda: datetime.now(timezone.utc).isoformat())

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    school_name: Mapped[str] = mapped_column(String(200), default="Trường học")
    days: Mapped[int] = mapped_column(Integer, default=6)
    sessions: Mapped[int] = mapped_column(Integer, default=2)
    periods_per_session: Mapped[int] = mapped_column(Integer, default=5)
    blocked_slots_json: Mapped[str] = mapped_column(Text, default="[]")
    share_token: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: secrets.token_urlsafe(16))
    created_at: Mapped[str] = mapped_column(String(40), default=lambda: datetime.now().isoformat(timespec="seconds"))

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
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id"), nullable=True)
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
        UniqueConstraint("project_id", "teacher_id", "subject_id", name="uq_teacher_subject"),
    )

class TeacherAccountLink(Base):
    __tablename__ = "teacher_account_links"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), unique=True, index=True)
    __table_args__ = (UniqueConstraint("user_id", "teacher_id", name="uq_teacher_account_link"),)

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
        UniqueConstraint("project_id", "grade_id", "subject_id", name="uq_grade_subject_requirement"),
    )

class SchoolClass(Base):
    __tablename__ = "classes"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    grade_id: Mapped[Optional[int]] = mapped_column(ForeignKey("grades.id"), nullable=True)
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
        UniqueConstraint("project_id", "class_id", "subject_id", name="uq_assignment_class_subject"),
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
    __table_args__ = (UniqueConstraint("project_id", "assignment_id", "slot", name="uq_lesson"),)

class TeacherPreference(Base):
    __tablename__ = "teacher_preferences"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    preferred_json: Mapped[str] = mapped_column(Text, default="[]")
    unavailable_json: Mapped[str] = mapped_column(Text, default="[]")
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    created_at: Mapped[str] = mapped_column(String(40), default=lambda: datetime.now().isoformat(timespec="seconds"))
    reviewed_at: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

class ChatbotErrorLog(Base):
    __tablename__ = "chatbot_error_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[str] = mapped_column(
        String(40),
        default=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"),
        index=True,
    )
    project_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    project_name: Mapped[str] = mapped_column(String(200), default="")
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    user_name: Mapped[str] = mapped_column(String(120), default="")
    user_email: Mapped[str] = mapped_column(String(255), default="")
    error_code: Mapped[str] = mapped_column(String(64), default="chatbot_error", index=True)
    provider_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str] = mapped_column(Text)

Base.metadata.create_all(engine)

def migrate_schema():
    """Bổ sung các cột cũ còn thiếu bằng câu lệnh tương thích PostgreSQL."""
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    role_was_added = "role" not in columns
    with engine.begin() as connection:
        if role_was_added:
            connection.exec_driver_sql(
                "ALTER TABLE users "
                "ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'pending'"
            )
        if "teacher_id" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN teacher_id INTEGER"
            )
        if "requested_teacher_name" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN requested_teacher_name VARCHAR(120)"
            )
        if "requested_project_id" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN requested_project_id INTEGER"
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_users_requested_project_id ON users (requested_project_id)"
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
        connection.exec_driver_sql(
            "UPDATE users SET role='pending' WHERE role IS NULL OR role='' OR role='user'"
        )
        # Luôn khôi phục vai trò từ các quan hệ dữ liệu cũ. Một số database cũ
        # đã có cột role nhưng vẫn lưu giá trị legacy "user"; chỉ chạy phần
        # này khi vừa thêm cột role sẽ khiến toàn bộ tài khoản bị kẹt ở pending.
        connection.exec_driver_sql(
            "UPDATE users SET role='teacher' "
            "WHERE teacher_id IS NOT NULL AND role='pending'"
        )
        bootstrap_email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
        try:
            configured_super_admin_id = int(os.getenv("SUPER_ADMIN_USER_ID", "0") or 0)
        except ValueError:
            configured_super_admin_id = 0
        if "projects" in inspector.get_table_names():
            # Chủ project thường giữ role admin. Chỉ tài khoản bootstrap do chủ
            # hệ thống cấu hình mới được nâng thành super_admin.
            if configured_super_admin_id > 0:
                connection.exec_driver_sql(
                    "UPDATE users SET role='admin', is_superadmin=FALSE "
                    "WHERE id IN (SELECT DISTINCT owner_id FROM projects) AND id<>%s",
                    (configured_super_admin_id,),
                )
            else:
                connection.exec_driver_sql(
                    "UPDATE users SET role='admin', is_superadmin=FALSE "
                    "WHERE id IN (SELECT DISTINCT owner_id FROM projects) "
                    "AND (%s='' OR lower(email)<>lower(%s))",
                    (bootstrap_email, bootstrap_email),
                )
        if "teacher_account_links" in inspector.get_table_names():
            connection.exec_driver_sql(
                "INSERT INTO teacher_account_links (user_id, teacher_id) "
                "SELECT id, teacher_id FROM users "
                "WHERE role='teacher' AND teacher_id IS NOT NULL "
                "ON CONFLICT (teacher_id) DO NOTHING"
            )
            # Admin không được tiếp tục chiếm hồ sơ giáo viên. Đồng thời sửa
            # dữ liệu lỗi đã được tạo bởi các phiên bản bootstrap cũ.
            connection.exec_driver_sql(
                "DELETE FROM teacher_account_links USING users "
                "WHERE teacher_account_links.user_id=users.id "
                "AND users.role IN ('admin', 'super_admin')"
            )
        connection.exec_driver_sql(
            "UPDATE users SET teacher_id=NULL, requested_teacher_name=NULL, "
            "requested_project_id=NULL WHERE role IN ('admin', 'super_admin')"
        )
        connection.exec_driver_sql(
            "ALTER TABLE users ALTER COLUMN role SET DEFAULT 'pending'"
        )
        if configured_super_admin_id > 0:
            connection.exec_driver_sql(
                "UPDATE users SET role=CASE WHEN role='super_admin' THEN 'admin' ELSE role END, "
                "is_superadmin=FALSE WHERE id<>%s",
                (configured_super_admin_id,),
            )
            connection.exec_driver_sql(
                "UPDATE users SET role='super_admin', is_superadmin=TRUE, teacher_id=NULL, "
                "requested_teacher_name=NULL, requested_project_id=NULL WHERE id=%s",
                (configured_super_admin_id,),
            )
            if "teacher_account_links" in inspector.get_table_names():
                connection.exec_driver_sql(
                    "DELETE FROM teacher_account_links WHERE user_id=%s",
                    (configured_super_admin_id,),
                )
        elif bootstrap_email:
            connection.exec_driver_sql(
                "UPDATE users SET role=CASE WHEN role='super_admin' THEN 'admin' ELSE role END, "
                "is_superadmin=FALSE WHERE lower(email)<>lower(%s)",
                (bootstrap_email,),
            )
            connection.exec_driver_sql(
                "UPDATE users SET role='super_admin', is_superadmin=TRUE, teacher_id=NULL, "
                "requested_teacher_name=NULL, requested_project_id=NULL "
                "WHERE lower(email)=lower(%s)",
                (bootstrap_email,),
            )
            if "teacher_account_links" in inspector.get_table_names():
                connection.exec_driver_sql(
                    "DELETE FROM teacher_account_links USING users "
                    "WHERE teacher_account_links.user_id=users.id "
                    "AND lower(users.email)=lower(%s)",
                    (bootstrap_email,),
                )

        # Từ phiên bản này, môn giáo viên có thể dạy được lưu riêng. Với dữ
        # liệu cũ, suy ra quan hệ này từ các phân công đã tồn tại để nâng cấp
        # không làm mất khả năng chỉnh sửa/xếp lịch của project hiện hữu.
        if "teacher_subjects" in inspector.get_table_names() and "assignments" in inspector.get_table_names():
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

        assignment_columns = {column["name"] for column in inspector.get_columns("assignments")} if "assignments" in inspector.get_table_names() else set()
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
            connection.exec_driver_sql(
                "UPDATE assignments SET consecutive_pattern=''"
            )

        fixed_columns = {column["name"] for column in inspector.get_columns("fixed_lessons")} if "fixed_lessons" in inspector.get_table_names() else set()
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

        # Bản demo cũ từng được tạo chỉ với một buổi. Khi mở thêm buổi chiều,
        # phải remap mọi slot theo tọa độ (ngày, buổi, tiết) cũ trước khi đổi
        # sessions; nếu chỉ UPDATE sessions thì slot của ngày 2+ sẽ bị hiểu thành
        # buổi chiều/ngày khác.
        if "projects" in inspector.get_table_names():
            project_columns = {column["name"] for column in inspector.get_columns("projects")}
            if "blocked_slots_json" not in project_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE projects ADD COLUMN blocked_slots_json TEXT NOT NULL DEFAULT '[]'"
                )
            legacy_demo_projects = connection.exec_driver_sql(
                "SELECT id, periods_per_session, blocked_slots_json FROM projects "
                "WHERE name='TKB học kỳ I' AND school_name='THPT Demo' AND sessions=1"
            ).mappings().all()
            for legacy_project in legacy_demo_projects:
                project_id = int(legacy_project["id"])
                periods_per_session = int(legacy_project["periods_per_session"])

                def remap_json_slots(raw_value):
                    return json.dumps(remap_slots_for_session_expansion(
                        parse_integer_set(raw_value),
                        old_sessions=1,
                        new_sessions=2,
                        periods_per_session=periods_per_session,
                    ))

                connection.exec_driver_sql(
                    "UPDATE projects SET blocked_slots_json=%s WHERE id=%s",
                    (remap_json_slots(legacy_project["blocked_slots_json"]), project_id),
                )

                for table_name in ("lessons", "fixed_lessons"):
                    if table_name not in inspector.get_table_names():
                        continue
                    rows = connection.exec_driver_sql(
                        f"SELECT id, slot FROM {table_name} WHERE project_id=%s",
                        (project_id,),
                    ).mappings().all()
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
                    rows = connection.exec_driver_sql(
                        f"SELECT {selected_columns} FROM {table_name} WHERE project_id=%s",
                        (project_id,),
                    ).mappings().all()
                    for row in rows:
                        assignments_sql = ", ".join(f"{column}=%s" for column in column_names)
                        values = tuple(remap_json_slots(row[column]) for column in column_names)
                        connection.exec_driver_sql(
                            f"UPDATE {table_name} SET {assignments_sql} WHERE id=%s",
                            (*values, row["id"]),
                        )

                connection.exec_driver_sql(
                    "UPDATE projects SET sessions=2 WHERE id=%s",
                    (project_id,),
                )

migrate_schema()
class Passwords:
    @staticmethod
    def hash(password: str) -> str:
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
        return f"pbkdf2_sha256${salt}${digest}"
    @staticmethod
    def verify(password: str, encoded: str) -> bool:
        try:
            algo, salt, digest = encoded.split("$", 2)
            if algo != "pbkdf2_sha256": return False
            actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
            return hmac.compare_digest(actual, digest)
        except Exception:
            return False
pwd = Passwords()
signer = URLSafeTimedSerializer(SECRET_KEY, salt="session")
reset_signer = URLSafeTimedSerializer(SECRET_KEY, salt="password-reset")
captcha_signer = URLSafeTimedSerializer(SECRET_KEY, salt="forgot-password-captcha")
registration_signer = URLSafeTimedSerializer(SECRET_KEY, salt="registration-verification")

app = FastAPI(title="Teacher Timetable")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

DAYS = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]
RESET_TOKEN_TTL_SECONDS = 30 * 60
REGISTRATION_OTP_TTL_SECONDS = 10 * 60
REGISTRATION_OTP_RESEND_SECONDS = 60
REGISTRATION_OTP_MAX_ATTEMPTS = 5
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
SEED_DEMO_DATA = os.getenv("SEED_DEMO_DATA", "false").strip().lower() in {"1", "true", "yes"}

def new_captcha(purpose: str = "password_reset") -> tuple[str, str]:
    variant = secrets.randbelow(3)
    if variant == 0:
        left, right = secrets.randbelow(31) + 10, secrets.randbelow(19) + 2
        question, expected = f"{left} + {right} = ?", left + right
    elif variant == 1:
        right = secrets.randbelow(18) + 2
        expected = secrets.randbelow(30) + 10
        left = expected + right
        question = f"{left} − {right} = ?"
    else:
        left, right, extra = secrets.randbelow(7) + 3, secrets.randbelow(6) + 2, secrets.randbelow(8) + 1
        question, expected = f"{left} × {right} + {extra} = ?", left * right + extra
    issued_at = int(datetime.now(timezone.utc).timestamp())
    nonce = secrets.token_urlsafe(18)
    answer_hash = hmac.new(
        SECRET_KEY.encode(),
        f"captcha:{purpose}:{nonce}:{expected}".encode(),
        hashlib.sha256,
    ).hexdigest()
    token = captcha_signer.dumps({
        "answer_hash": answer_hash,
        "purpose": purpose,
        "issued_at": issued_at,
        "nonce": nonce,
    })
    return question, token

def captcha_is_valid(token: str, answer: str, purpose: str = "password_reset") -> bool:
    try:
        data = captcha_signer.loads(token, max_age=5 * 60)
        age = int(datetime.now(timezone.utc).timestamp()) - int(data["issued_at"])
        submitted_hash = hmac.new(
            SECRET_KEY.encode(),
            f"captcha:{purpose}:{data['nonce']}:{answer.strip()}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return (
            data["purpose"] == purpose
            and 2 <= age <= 5 * 60
            and hmac.compare_digest(str(data["answer_hash"]), submitted_hash)
        )
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return False

def send_email_message(recipient: str, subject: str, body: str) -> bool:
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    if not smtp_host:
        return False

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "no-reply@smart-tkb.local").strip()
    use_ssl = os.getenv("SMTP_SSL", "false").strip().lower() in {"1", "true", "yes"}
    use_starttls = os.getenv("SMTP_STARTTLS", "true").strip().lower() in {"1", "true", "yes"}
    timeout = max(5, int(os.getenv("SMTP_TIMEOUT_SECONDS", "30")))

    # Gmail SMTP always requires authentication. A missing credential should fail loudly
    # in the server log instead of silently pretending that the message was sent.
    if smtp_host.lower() == "smtp.gmail.com" and (not smtp_user or not smtp_password):
        raise smtplib.SMTPAuthenticationError(535, b"Missing SMTP_USER or SMTP_PASSWORD")

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

def send_registration_otp_email(recipient: str, otp: str, project_name: str) -> bool:
    return send_email_message(
        recipient,
        "Mã xác nhận đăng ký Smart TKB",
        f"Mã OTP đăng ký tài khoản của bạn là: {otp}\n\n"
        f"Bộ thời khóa biểu: {project_name}\n"
        "Mã có hiệu lực trong 10 phút và chỉ dùng được một lần.\n\n"
        "Nếu bạn không thực hiện đăng ký này, hãy bỏ qua email.",
    )

def registration_otp_hash(email: str, otp: str) -> str:
    return hmac.new(SECRET_KEY.encode(), f"{email}:{otp}".encode(), hashlib.sha256).hexdigest()

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
        return user
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        raise HTTPException(401)

def is_admin(user: User) -> bool:
    return user.role in ADMIN_ROLES

def is_super_admin(user: User) -> bool:
    return user.role == "super_admin"

def get_project(pid: int, user: User, db: Session) -> Project:
    if not is_admin(user):
        raise HTTPException(403,"Chỉ quản trị viên được thực hiện thao tác này")
    p = db.get(Project, pid)
    if not p or (not is_super_admin(user) and p.owner_id != user.id):
        raise HTTPException(404)
    return p

def get_project_for_update(pid: int, user: User, db: Session) -> Project:
    """Khóa project đến hết transaction để tuần tự hóa mọi thay đổi lịch."""
    if not is_admin(user):
        raise HTTPException(403,"Chỉ quản trị viên được thực hiện thao tác này")
    query = select(Project).where(Project.id == pid)
    if not is_super_admin(user):
        query = query.where(Project.owner_id == user.id)
    project = db.scalar(query.with_for_update())
    if not project:
        raise HTTPException(404)
    return project

def admin_project_ids(user: User, db: Session) -> set[int]:
    if not is_admin(user):
        return set()
    if is_super_admin(user):
        return set(db.scalars(select(Project.id)).all())
    return set(db.scalars(select(Project.id).where(Project.owner_id == user.id)).all())

def admin_teacher_ids(user: User, db: Session) -> set[int]:
    project_ids = admin_project_ids(user, db)
    if not project_ids:
        return set()
    return set(db.scalars(select(Teacher.id).where(Teacher.project_id.in_(project_ids))).all())

def account_teacher_ids(account: User, db: Session) -> set[int]:
    ids = set(db.scalars(
        select(TeacherAccountLink.teacher_id).where(TeacherAccountLink.user_id == account.id)
    ).all())
    if account.teacher_id is not None:
        ids.add(account.teacher_id)
    return ids

def account_for_teacher(teacher_id: int, db: Session) -> User | None:
    link = db.scalar(select(TeacherAccountLink).where(TeacherAccountLink.teacher_id == teacher_id))
    if link:
        return db.get(User, link.user_id)
    return db.scalar(select(User).where(User.role == "teacher", User.teacher_id == teacher_id))

def ensure_teacher_link(account: User, teacher: Teacher, db: Session) -> None:
    existing = db.scalar(select(TeacherAccountLink).where(TeacherAccountLink.teacher_id == teacher.id))
    if existing and existing.user_id != account.id:
        raise HTTPException(409, "Giáo viên này đã có tài khoản")
    if not existing:
        db.add(TeacherAccountLink(user_id=account.id, teacher_id=teacher.id))
    if account.teacher_id is None:
        account.teacher_id = teacher.id

def is_bootstrap_admin(user: User, db: Session) -> bool:
    return is_super_admin(user)

def admin_can_manage_account(admin: User, account: User, db: Session) -> bool:
    if not is_admin(admin):
        return False
    if account.id == admin.id:
        return True
    if is_super_admin(admin):
        return account.role != "super_admin"
    if account.role in ADMIN_ROLES:
        return False
    project_ids = admin_project_ids(admin, db)
    if account.role == "teacher":
        teacher_ids = account_teacher_ids(account, db)
        if not teacher_ids:
            return False
        return db.scalar(select(Teacher.id).where(
            Teacher.id.in_(teacher_ids), Teacher.project_id.in_(project_ids)
        )) is not None
    if account.role == "pending":
        if account.requested_project_id in project_ids:
            return True
        return account.requested_project_id is None and is_bootstrap_admin(admin, db)
    return False

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

def consecutive_groups(pattern:str,total_periods:int):
    """Đọc mẫu cụm cũ, chỉ dùng cho migration/tương thích dữ liệu cũ."""
    text=(pattern or "").strip()
    if not text: return [1]*total_periods
    try:
        groups=[int(value.strip()) for value in text.split(",") if value.strip()]
    except ValueError as exc:
        raise ValueError("Mẫu tiết liên tiếp cũ không hợp lệ.") from exc
    if not groups or any(value<1 for value in groups) or sum(groups)!=total_periods:
        raise ValueError("Mẫu tiết liên tiếp cũ không hợp lệ.")
    return groups

def normalized_block_mode(value:str,total_periods:int,subject:Subject,project:Project):
    mode=(value or "free").strip().lower()
    aliases={
        "prefer_double":"preferred_double",
        "preferred":"preferred_double",
        "required":"required_double",
        "double":"required_double",
    }
    mode=aliases.get(mode,mode)
    if mode not in BLOCK_MODES:
        raise ValueError("Chế độ xếp tiết không hợp lệ.")
    total_slots=project.days*project.sessions*project.periods_per_session
    if total_periods>total_slots:
        raise ValueError(f"Số tiết/tuần không được vượt quá {total_slots} ô của thời khóa biểu.")
    if mode in {"preferred_double","required_double"} and total_periods>=2:
        if subject.max_consecutive<2:
            raise ValueError(
                f"Môn {subject.name} đang giới hạn tối đa {subject.max_consecutive} tiết liên tiếp; "
                "hãy tăng giới hạn lên ít nhất 2 trước khi chọn chế độ tiết đôi."
            )
        if project.periods_per_session<2:
            raise ValueError("Mỗi buổi phải có ít nhất 2 tiết để dùng chế độ tiết đôi.")
    if mode=="required_double":
        groups=[2]*(total_periods//2)+([1] if total_periods%2 else [])
        if not timetable_pattern_feasible(project,groups):
            raise ValueError(
                "Số cặp tiết bắt buộc không thể phân bố trong số ngày, buổi và tiết hiện có."
            )
    return mode

def assignment_requires_double(assignment:Assignment):
    return getattr(assignment,"block_mode","free")=="required_double"

def assignment_prefers_double(assignment:Assignment):
    return getattr(assignment,"block_mode","free")=="preferred_double"

def assignment_groups(assignment:Assignment):
    total=max(0,int(assignment.periods_per_week or 0))
    if assignment_requires_double(assignment):
        return [2]*(total//2)+([1] if total%2 else [])
    return [1]*total

def assignment_generated_pattern(assignment:Assignment):
    return ",".join(str(value) for value in assignment_groups(assignment)) if assignment_requires_double(assignment) else ""

def assignment_mode_label(assignment:Assignment):
    labels={
        "free":"Tự do",
        "preferred_double":"Ưu tiên tiết đôi",
        "required_double":"Bắt buộc tiết đôi",
    }
    return labels.get(getattr(assignment,"block_mode","free"),"Tự do")

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

def bounded_int(value,default:int,minimum:int,maximum:int,label:str):
    raw=default if value in (None,"") else value
    if isinstance(raw,bool) or isinstance(raw,float) and not raw.is_integer():
        raise HTTPException(400,f"{label} phải là số nguyên từ {minimum} đến {maximum}")
    try:
        parsed=int(raw)
    except (TypeError,ValueError) as exc:
        raise HTTPException(400,f"{label} phải là số nguyên từ {minimum} đến {maximum}") from exc
    if not minimum<=parsed<=maximum:
        raise HTTPException(400,f"{label} phải nằm trong khoảng từ {minimum} đến {maximum}")
    return parsed

def pattern_slots_match(project:Project,pattern:str,total_periods:int,slots:list[int] | set[int]):
    """Kiểm tra các cụm tiết thực tế có đúng mẫu đã khai báo hay không."""
    try:
        expected=sorted(consecutive_groups(pattern,total_periods))
    except ValueError:
        return False
    if len(slots)!=total_periods:
        return False
    ppd=project.sessions*project.periods_per_session
    groups=defaultdict(list)
    for slot in sorted(set(slots)):
        day=slot//ppd
        inside=slot%ppd
        session=inside//project.periods_per_session
        period=inside%project.periods_per_session
        groups[(day,session)].append(period)
    actual=[]
    for periods in groups.values():
        run=1
        for left,right in zip(periods,periods[1:]):
            if right==left+1:
                run+=1
            else:
                actual.append(run);run=1
        actual.append(run)
    return sorted(actual)==expected

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
                runs.append({"start": current[0][1], "size": len(current), "slots": [x[1] for x in current]})
                current = [item]
        if current:
            runs.append({"start": current[0][1], "size": len(current), "slots": [x[1] for x in current]})
    return sorted(runs, key=lambda item: item["start"])

def _pack_pattern_groups_into_segments(group_sizes:list[int],segments:list[tuple[int,int]]):
    """Xếp các cụm chưa neo vào những đoạn trống, cách nhau ít nhất một tiết."""
    items=sorted((int(size) for size in group_sizes),reverse=True)
    if not items:
        return []
    usable=[(start,length) for start,length in segments if length>0]
    capacities=[length+1 for _start,length in usable]
    if sum(size+1 for size in items)>sum(capacities):
        return None
    allocations=[[] for _segment in usable]
    failed=set()

    def search(index:int):
        if index==len(items):
            return True
        state=(index,tuple(sorted(capacities,reverse=True)))
        if state in failed:
            return False
        size=items[index]
        weight=size+1
        seen_capacities=set()
        for segment_index,capacity in enumerate(capacities):
            if capacity<weight or capacity in seen_capacities:
                continue
            seen_capacities.add(capacity)
            capacities[segment_index]-=weight
            allocations[segment_index].append(size)
            if search(index+1):
                return True
            allocations[segment_index].pop()
            capacities[segment_index]+=weight
        failed.add(state)
        return False

    if not search(0):
        return None
    placements=[]
    for (segment_start,_length),sizes in zip(usable,allocations):
        cursor=segment_start
        for size in sizes:
            placements.append((size,cursor))
            cursor+=size+1
    return placements

def _complete_pattern_placement(
    project:Project,
    expected:list[int],
    slots:list[int] | set[int],
    forced_placements:list[tuple[int,int]] | None=None,
):
    """Tìm một cách đặt đầy đủ các cụm, đồng thời chứa chính xác các tiết đã có."""
    values=list(slots)
    current=set(values)
    maximum=project.days*project.sessions*project.periods_per_session
    if len(values)!=len(current) or any(slot<0 or slot>=maximum for slot in current):
        return None
    if len(current)>sum(expected) or any(size<1 or size>project.periods_per_session for size in expected):
        return None

    ppd=project.sessions*project.periods_per_session
    periods_per_session=project.periods_per_session
    starts_by_size={}
    for size in set(expected):
        starts=[]
        for day in range(project.days):
            for session in range(project.sessions):
                base=day*ppd+session*periods_per_session
                starts.extend(base+period for period in range(periods_per_session-size+1))
        starts_by_size[size]=starts

    def interval(start:int,size:int):
        return set(range(start,start+size))

    def compatible(left_start:int,left_size:int,right_start:int,right_size:int):
        left_slots=interval(left_start,left_size)
        right_slots=interval(right_start,right_size)
        if left_slots.intersection(right_slots):
            return False
        left_day,left_session,_=slot_meta(project,left_start)
        right_day,right_session,_=slot_meta(project,right_start)
        if (left_day,left_session)!=(right_day,right_session):
            return True
        return left_start+left_size!=right_start and right_start+right_size!=left_start

    def free_segments(selected:list[tuple[int,int,set[int]]]):
        forbidden=defaultdict(set)
        for size,start,_covered in selected:
            day,session,period=slot_meta(project,start)
            key=(day,session)
            forbidden[key].update(range(period,period+size))
            if period>0:
                forbidden[key].add(period-1)
            if period+size<periods_per_session:
                forbidden[key].add(period+size)
        result=[]
        for day in range(project.days):
            for session in range(project.sessions):
                blocked=forbidden[(day,session)]
                base=day*ppd+session*periods_per_session
                start=None
                for period in range(periods_per_session+1):
                    is_free=period<periods_per_session and period not in blocked
                    if is_free and start is None:
                        start=period
                    elif not is_free and start is not None:
                        result.append((base+start,period-start))
                        start=None
        return result

    remaining=Counter(expected)
    selected=[]
    forced_covered=set()
    for size,start in forced_placements or []:
        if remaining[size]<=0 or start not in starts_by_size.get(size,[]):
            return None
        covered=current.intersection(interval(start,size))
        if not covered or forced_covered.intersection(covered):
            return None
        if any(not compatible(start,size,other_start,other_size) for other_size,other_start,_ in selected):
            return None
        remaining[size]-=1
        selected.append((size,start,set(covered)))
        forced_covered.update(covered)
    failed=set()

    def search(uncovered:frozenset[int]):
        state=(
            tuple(sorted(uncovered)),
            tuple(sorted(remaining.items())),
            tuple(sorted((size,start) for size,start,_covered in selected)),
        )
        if state in failed:
            return None
        if not uncovered:
            rest=[]
            for size,count in remaining.items():
                rest.extend([size]*count)
            packed=_pack_pattern_groups_into_segments(rest,free_segments(selected))
            if packed is None:
                failed.add(state)
                return None
            return [*selected,*[(size,start,set()) for size,start in packed]]

        target=min(uncovered)
        for size in sorted((value for value,count in remaining.items() if count>0),reverse=True):
            for start in starts_by_size[size]:
                target_slots=interval(start,size)
                covered=current.intersection(target_slots)
                if target not in covered or not covered.issubset(uncovered):
                    continue
                if any(not compatible(start,size,other_start,other_size) for other_size,other_start,_ in selected):
                    continue
                remaining[size]-=1
                selected.append((size,start,set(covered)))
                result=search(frozenset(set(uncovered)-covered))
                if result is not None:
                    return result
                selected.pop()
                remaining[size]+=1
        failed.add(state)
        return None

    return search(frozenset(current-forced_covered))

def timetable_pattern_feasible(project:Project,groups:list[int]):
    return _complete_pattern_placement(project,groups,set()) is not None

def pattern_completion_plan(project: Project, assignment: Assignment, slots: list[int] | set[int]):
    """Lập kế hoạch hoàn thành mẫu tiết từ phần lịch hiện có.

    Các tiết đã đặt có thể là một đoạn liền hoặc nhiều mảnh của cùng một cụm
    (ví dụ đã có tiết 1 và 3 của cụm 3 tiết). Hàm tìm cách bao phủ toàn bộ các
    tiết hiện có bằng những cụm hợp lệ, rồi trả về phần còn thiếu của mỗi cụm.
    """
    current=set(slots)
    maximum=project.days*project.sessions*project.periods_per_session
    if len(current)!=len(list(slots)) or len(current)>assignment.periods_per_week:
        return None
    if any(slot<0 or slot>=maximum for slot in current):
        return None
    if not assignment_requires_double(assignment):
        return [{
            "size":1,
            "anchor_slots":tuple(),
            "candidate_starts":None,
        } for _ in range(assignment.periods_per_week-len(current))]
    expected=assignment_groups(assignment)
    placements=_complete_pattern_placement(project,expected,current)
    if placements is None:
        return None
    ppd=project.sessions*project.periods_per_session
    plan = []
    for target_size,start,covered in placements:
        if not covered:
            plan.append({
                "size": target_size,
                "anchor_slots": tuple(),
                "candidate_starts": None,
            })
            continue
        if len(covered)==target_size:
            continue
        alternative_starts=[]
        for day in range(project.days):
            for session in range(project.sessions):
                base=day*ppd+session*project.periods_per_session
                for period in range(project.periods_per_session-target_size+1):
                    candidate=base+period
                    candidate_slots=set(range(candidate,candidate+target_size))
                    if current.intersection(candidate_slots)!=covered:
                        continue
                    # Chỉ ép candidate của chính cụm đang xét. Các cụm neo còn
                    # lại phải được phép tự chọn lại vị trí; nếu ghim chúng theo
                    # một nghiệm tạm thời, ta có thể loại nhầm một candidate mà
                    # thực tế thuộc một nghiệm hoàn chỉnh khác.
                    if _complete_pattern_placement(
                        project, expected, slots, [(target_size,candidate)]
                    ) is not None:
                        alternative_starts.append(candidate)
        plan.append({
            "size": target_size,
            "anchor_slots": tuple(sorted(covered)),
            "candidate_starts": tuple(sorted(set(alternative_starts or [start]))),
        })
    return plan


def remaining_pattern_groups(project: Project, assignment: Assignment, slots: list[int] | set[int]):
    """Trả về kích thước đầy đủ của các cụm còn phải hoàn thành."""
    plan = pattern_completion_plan(project, assignment, slots)
    if plan is None:
        return None
    return [item["size"] for item in plan]

def assignment_pattern_matches(project:Project,assignment:Assignment,slots:list[int] | set[int]):
    values=list(slots)
    if len(values)!=len(set(values)) or len(values)!=assignment.periods_per_week:
        return False
    if not assignment_requires_double(assignment):
        return True
    return pattern_slots_match(
        project,
        assignment_generated_pattern(assignment),
        assignment.periods_per_week,
        values,
    )

def partial_assignment_pattern_matches(project:Project,assignment:Assignment,slots:list[int] | set[int]):
    return pattern_completion_plan(project,assignment,slots) is not None


def assignment_completion_feasible(
    db: Session,
    project: Project,
    assignment: Assignment,
    proposed_slots: list[int] | set[int],
) -> bool:
    """Kiểm tra phần lịch thủ công có ít nhất một cách hoàn thành hợp lệ.

    Khác với ``partial_assignment_pattern_matches``, hàm này xét cả các ràng
    buộc thực tế: ô khóa, thời gian tránh, trùng lớp/giáo viên, số tiết tối đa
    trong ngày, giới hạn tiết liên tiếp và các cụm cố định.
    """
    values=list(proposed_slots)
    current=set(values)
    maximum=project.days*project.sessions*project.periods_per_session
    if len(values)!=len(current) or len(current)>assignment.periods_per_week:
        return False
    if any(slot<0 or slot>=maximum for slot in current):
        return False
    expected=assignment_groups(assignment)
    keep_groups_separate=assignment_requires_double(assignment)

    teacher=db.get(Teacher,assignment.teacher_id)
    school_class=db.get(SchoolClass,assignment.class_id)
    subject=db.get(Subject,assignment.subject_id)
    if not teacher or not school_class or not subject:
        return False

    ppd=project.sessions*project.periods_per_session
    global_blocked=parse_slots(project.blocked_slots_json)
    teacher_unavailable=parse_slots(teacher.unavailable_json)
    class_unavailable=parse_slots(school_class.unavailable_json)
    accepted_preferred,accepted_unavailable=accepted_teacher_preferences(db,project.id)
    preferred=accepted_preferred.get(teacher.id,set())
    teacher_unavailable.update(accepted_unavailable.get(teacher.id,set()))

    other_lessons=[]
    for lesson in db.scalars(select(Lesson).where(Lesson.project_id==project.id)).all():
        if lesson.assignment_id!=assignment.id:
            other_lessons.append(lesson)

    teacher_busy=set()
    class_busy=set()
    teacher_day=Counter()
    base_subject_periods=defaultdict(set)
    for lesson in other_lessons:
        other=db.get(Assignment,lesson.assignment_id)
        if not other:
            continue
        day=lesson.slot//ppd
        if other.teacher_id==assignment.teacher_id:
            teacher_busy.add(lesson.slot)
            teacher_day[day]+=1
        if other.class_id==assignment.class_id:
            class_busy.add(lesson.slot)
            if other.subject_id==assignment.subject_id:
                inside=lesson.slot%ppd
                session=inside//project.periods_per_session
                period=inside%project.periods_per_session
                base_subject_periods[(day,session)].add(period)

    forbidden=global_blocked|teacher_unavailable|class_unavailable|teacher_busy|class_busy
    if current.intersection(forbidden):
        return False

    starts_by_size={}
    for size in set(expected):
        candidates=[]
        for day in range(project.days):
            for session in range(project.sessions):
                base=day*ppd+session*project.periods_per_session
                for period in range(project.periods_per_session-size+1):
                    start=base+period
                    group=tuple(range(start,start+size))
                    if not set(group).intersection(forbidden):
                        candidates.append((start,group))
        starts_by_size[size]=candidates

    def compatible(left_start:int,left_size:int,right_start:int,right_size:int):
        left_end=left_start+left_size
        right_end=right_start+right_size
        if left_start<right_end and right_start<left_end:
            return False
        left_day,left_session,_=slot_meta(project,left_start)
        right_day,right_session,_=slot_meta(project,right_start)
        if (left_day,left_session)!=(right_day,right_session):
            return True
        if not keep_groups_separate:
            return True
        return left_end!=right_start and right_end!=left_start

    remaining=Counter(expected)
    selected=[]
    selected_slots=set()
    added_teacher_day=Counter()
    added_subject_periods=defaultdict(set)

    def subject_limit_ok(group:tuple[int,...]):
        touched=set()
        for slot in group:
            day=slot//ppd
            inside=slot%ppd
            session=inside//project.periods_per_session
            period=inside%project.periods_per_session
            touched.add((day,session))
            added_subject_periods[(day,session)].add(period)
        valid=True
        for key in touched:
            periods=sorted(base_subject_periods[key]|added_subject_periods[key])
            longest=run=0
            previous=None
            for period in periods:
                run=run+1 if previous is not None and period==previous+1 else 1
                longest=max(longest,run)
                previous=period
            if longest>subject.max_consecutive:
                valid=False
                break
        for slot in group:
            day=slot//ppd
            inside=slot%ppd
            session=inside//project.periods_per_session
            period=inside%project.periods_per_session
            added_subject_periods[(day,session)].discard(period)
        return valid

    same_assignment_lessons=db.scalars(select(Lesson).where(
        Lesson.project_id==project.id,
        Lesson.assignment_id==assignment.id,
    )).all()
    fixed_rows=db.scalars(select(FixedLesson).where(
        FixedLesson.project_id==project.id,
        FixedLesson.assignment_id==assignment.id,
    )).all()

    fixed_placements=[]
    for row in fixed_rows:
        size=fixed_row_size(project,assignment,row,same_assignment_lessons)
        if remaining[size]<=0:
            return False
        group=tuple(range(row.slot,row.slot+size))
        if (row.slot,group) not in starts_by_size.get(size,[]):
            return False
        if any(not compatible(row.slot,size,start,other_size) for other_size,start,_group in fixed_placements):
            return False
        fixed_placements.append((size,row.slot,group))
        remaining[size]-=1

    def add_group(size:int,start:int,group:tuple[int,...]):
        day_counts=Counter(slot//ppd for slot in group)
        for day,count in day_counts.items():
            if teacher_day[day]+added_teacher_day[day]+count>teacher.max_periods_day:
                return False
        if not subject_limit_ok(group):
            return False
        for day,count in day_counts.items():
            added_teacher_day[day]+=count
        for slot in group:
            day=slot//ppd
            inside=slot%ppd
            session=inside//project.periods_per_session
            period=inside%project.periods_per_session
            added_subject_periods[(day,session)].add(period)
        selected.append((size,start,group))
        selected_slots.update(group)
        return True

    def remove_group(size:int,start:int,group:tuple[int,...]):
        selected.pop()
        for slot in group:
            selected_slots.remove(slot)
            day=slot//ppd
            added_teacher_day[day]-=1
            inside=slot%ppd
            session=inside//project.periods_per_session
            period=inside%project.periods_per_session
            added_subject_periods[(day,session)].discard(period)

    for size,start,group in fixed_placements:
        if set(group).intersection(selected_slots) or not add_group(size,start,group):
            return False

    failed=set()
    def search():
        uncovered=current-selected_slots
        if sum(remaining.values())==0:
            return not uncovered and len(selected_slots)==assignment.periods_per_week
        state=(
            tuple(sorted(remaining.items())),
            tuple(sorted(uncovered)),
            tuple(sorted(selected_slots)),
        )
        if state in failed:
            return False

        candidate_sets=[]
        if uncovered:
            target=min(uncovered)
            for size,count in remaining.items():
                if count<=0:
                    continue
                options=[item for item in starts_by_size[size] if target in item[1]]
                if options:
                    candidate_sets.append((len(options),-size,size,options))
        else:
            for size,count in remaining.items():
                if count<=0:
                    continue
                options=starts_by_size[size]
                candidate_sets.append((len(options),-size,size,options))
        if not candidate_sets:
            failed.add(state)
            return False

        for _count,_neg,size,raw_options in sorted(candidate_sets):
            options=sorted(raw_options,key=lambda item:(
                -sum(slot in preferred for slot in item[1]),
                item[0],
            ))
            for start,group in options:
                group_set=set(group)
                if group_set.intersection(selected_slots):
                    continue
                if any(not compatible(start,size,other_start,other_size) for other_size,other_start,_other_group in selected):
                    continue
                if uncovered and not group_set.intersection(uncovered):
                    continue
                if not add_group(size,start,group):
                    continue
                remaining[size]-=1
                if search():
                    return True
                remaining[size]+=1
                remove_group(size,start,group)
        failed.add(state)
        return False

    return search()


def assignment_pattern_label(assignment:Assignment):
    if assignment_requires_double(assignment):
        return "bắt buộc tiết đôi ("+" + ".join(str(value) for value in assignment_groups(assignment))+")"
    if assignment_prefers_double(assignment):
        return "ưu tiên tiết đôi"
    return "xếp tiết tự do"

def accepted_teacher_preferences(db: Session, project_id: int):
    rows = db.scalars(
        select(TeacherPreference).where(
            TeacherPreference.project_id == project_id,
            TeacherPreference.status == "accepted",
        )
    ).all()
    preferred = defaultdict(set)
    unavailable = defaultdict(set)
    for row in rows:
        preferred[row.teacher_id].update(parse_slots(row.preferred_json))
        unavailable[row.teacher_id].update(parse_slots(row.unavailable_json))
    return preferred, unavailable


def bounded_text(value, label: str, max_length: int, *, required: bool = True) -> str:
    cleaned = str(value or "").strip()
    if required and not cleaned:
        raise HTTPException(400, f"{label} không được để trống")
    if len(cleaned) > max_length:
        raise HTTPException(400, f"{label} không được vượt quá {max_length} ký tự")
    return cleaned

@app.exception_handler(401)
async def auth_error(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"ok": False, "message": "Phiên đăng nhập đã hết hạn."}, status_code=401)
    return RedirectResponse("/login", 303)

@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(db_session)):
    raw = request.cookies.get("session")
    if raw:
        try:
            data=signer.loads(raw,max_age=SESSION_TTL_SECONDS); user=db.get(User,int(data["uid"]))
            if user and int(data.get("sv",-1))==user.session_version:
                destination = "/teacher" if user.role == "teacher" else ("/projects" if is_admin(user) else "/account-pending")
                return RedirectResponse(destination, 303)
        except (BadSignature,SignatureExpired,KeyError,TypeError,ValueError):
            pass
    return templates.TemplateResponse("landing.html", {"request": request})

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("auth.html", {"request": request, "mode": "login", "error": None})

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(db_session)):
    user = db.scalar(select(User).where(User.email == email.lower().strip()))
    if not user or not pwd.verify(password, user.password_hash):
        return templates.TemplateResponse("auth.html", {"request": request, "mode": "login", "error": "Email hoặc mật khẩu không đúng"}, status_code=400)
    destination = "/teacher" if user.role == "teacher" else ("/projects" if is_admin(user) else "/account-pending")
    res = RedirectResponse(destination, 303)
    set_session_cookie(res, user)
    return res

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, project: str = "", db: Session = Depends(db_session)):
    target_project = db.scalar(select(Project).where(Project.share_token == project)) if project else None
    available_teachers = []
    if target_project:
        assigned_teacher_ids = set(db.scalars(select(TeacherAccountLink.teacher_id)).all())
        assigned_teacher_ids.update(db.scalars(
            select(User.teacher_id).where(User.role == "teacher", User.teacher_id.is_not(None))
        ).all())
        available_teachers = db.scalars(select(Teacher).where(
            Teacher.project_id == target_project.id,
            Teacher.id.not_in(assigned_teacher_ids),
        ).order_by(Teacher.name.asc())).all()
    captcha_question, captcha_token = new_captcha("registration")
    return templates.TemplateResponse("auth.html", {
        "request": request, "mode": "register", "error": None,
        "target_project": target_project, "project_token": project if target_project else "",
        "available_teachers": available_teachers,
        "captcha_question": captcha_question,
        "captcha_token": captcha_token,
        "form_values": {},
    })

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
        query = select(RegistrationVerification).where(RegistrationVerification.id == int(data["id"]))
        if lock:
            query = query.with_for_update()
        verification = db.scalar(query)
        nonce_hash = hashlib.sha256(str(data["nonce"]).encode()).hexdigest()
        if not verification or not hmac.compare_digest(verification.token_hash, nonce_hash):
            return None
        return verification
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None

def registration_otp_context(
    request: Request,
    verification: RegistrationVerification | None,
    verification_token: str,
    db: Session,
    error: str | None = None,
):
    question, captcha_token = new_captcha("registration_resend")
    project = db.get(Project, verification.project_id) if verification else None
    return {
        "request": request,
        "mode": "register_otp",
        "error": error,
        "verification_token": verification_token,
        "masked_email": mask_email(verification.email) if verification else "email của bạn",
        "target_project": project,
        "captcha_question": question,
        "captcha_token": captcha_token,
    }

@app.post("/register")
def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    teacher_id: int = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    project_token: str = Form(""),
    captcha_answer: str = Form(...),
    captcha_token: str = Form(...),
    human_confirm: Optional[str] = Form(None),
    website: str = Form(""),
    db: Session = Depends(db_session),
):
    name = name.strip()
    email = email.lower().strip()
    target_project = db.scalar(
        select(Project).where(Project.share_token == project_token).with_for_update()
    ) if project_token else None
    assigned_teacher_ids = set(db.scalars(select(TeacherAccountLink.teacher_id)).all())
    assigned_teacher_ids.update(db.scalars(
        select(User.teacher_id).where(User.role == "teacher", User.teacher_id.is_not(None))
    ).all())
    available_teachers = db.scalars(select(Teacher).where(
        Teacher.project_id == target_project.id,
        Teacher.id.not_in(assigned_teacher_ids),
    ).order_by(Teacher.name.asc())).all() if target_project else []
    fresh_question, fresh_captcha_token = new_captcha("registration")
    context = {
        "request": request, "mode": "register", "error": None,
        "target_project": target_project, "project_token": project_token if target_project else "",
        "available_teachers": available_teachers,
        "captcha_question": fresh_question,
        "captcha_token": fresh_captcha_token,
        "form_values": {"name": name, "email": email, "teacher_id": teacher_id},
    }
    if not target_project:
        context["error"] = "Bạn cần dùng liên kết mời hợp lệ của bộ thời khóa biểu để đăng ký."
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if website.strip() or human_confirm != "yes" or not captcha_is_valid(captcha_token, captcha_answer, "registration"):
        context["error"] = "Xác minh bảo mật không hợp lệ hoặc thao tác quá nhanh. Hãy giải câu hỏi mới."
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if not name:
        context["error"] = "Họ tên tài khoản không được để trống"
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if len(name) > 120:
        context["error"] = "Họ tên tài khoản không được vượt quá 120 ký tự"
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
    teacher = db.scalar(select(Teacher).where(
        Teacher.id == teacher_id,
        Teacher.project_id == target_project.id,
    ).with_for_update())
    if not teacher or account_for_teacher(teacher_id, db):
        context["error"] = "Hồ sơ giáo viên không còn khả dụng. Hãy tải lại liên kết mời."
        return templates.TemplateResponse("auth.html", context, status_code=409)

    now = datetime.now(timezone.utc)
    for expired in db.scalars(select(RegistrationVerification).where(
        RegistrationVerification.expires_at <= now.isoformat()
    )).all():
        db.delete(expired)
    db.flush()
    email_verification = db.scalar(select(RegistrationVerification).where(
        RegistrationVerification.email == email
    ).with_for_update())
    teacher_verification = db.scalar(select(RegistrationVerification).where(
        RegistrationVerification.teacher_id == teacher.id
    ).with_for_update())
    active_teacher_verification = teacher_verification and datetime.fromisoformat(teacher_verification.expires_at) > now
    if active_teacher_verification and teacher_verification.email != email:
        context["error"] = "Hồ sơ giáo viên này đang được xác minh bởi một email khác. Hãy thử lại sau 10 phút."
        return templates.TemplateResponse("auth.html", context, status_code=409)
    if email_verification and datetime.fromisoformat(email_verification.resend_available_at) > now:
        context["error"] = "Mã OTP vừa được gửi tới email này. Vui lòng chờ 60 giây trước khi gửi lại."
        return templates.TemplateResponse("auth.html", context, status_code=429)

    otp = f"{secrets.randbelow(1_000_000):06d}"
    nonce = secrets.token_urlsafe(32)
    try:
        if not send_registration_otp_email(email, otp, target_project.name):
            raise RuntimeError("SMTP chưa được cấu hình")
    except (OSError, smtplib.SMTPException, RuntimeError, ValueError) as exc:
        logger.exception("Could not send registration OTP to %s: %s", email, exc)
        context["error"] = "Chưa thể gửi mã OTP. Vui lòng kiểm tra email hoặc thử lại sau."
        return templates.TemplateResponse("auth.html", context, status_code=503)

    old_rows = {row.id: row for row in (email_verification, teacher_verification) if row is not None}
    for row in old_rows.values():
        db.delete(row)
    db.flush()
    verification = RegistrationVerification(
        email=email,
        name=name,
        password_hash=pwd.hash(password),
        project_id=target_project.id,
        teacher_id=teacher.id,
        otp_hash=registration_otp_hash(email, otp),
        token_hash=hashlib.sha256(nonce.encode()).hexdigest(),
        expires_at=(now + timedelta(seconds=REGISTRATION_OTP_TTL_SECONDS)).isoformat(),
        resend_available_at=(now + timedelta(seconds=REGISTRATION_OTP_RESEND_SECONDS)).isoformat(),
        attempt_count=0,
    )
    db.add(verification)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        context["error"] = "Email hoặc hồ sơ giáo viên đang được xác minh ở một phiên khác. Hãy thử lại sau."
        return templates.TemplateResponse("auth.html", context, status_code=409)
    verification_token = registration_signer.dumps({"id": verification.id, "nonce": nonce})
    resend_question, resend_captcha = new_captcha("registration_resend")
    return templates.TemplateResponse("auth.html", {
        "request": request,
        "mode": "register_otp",
        "error": None,
        "verification_token": verification_token,
        "masked_email": mask_email(email),
        "target_project": target_project,
        "captcha_question": resend_question,
        "captcha_token": resend_captcha,
    })

@app.post("/register/verify", response_class=HTMLResponse)
def verify_registration_otp(
    request: Request,
    verification_token: str = Form(...),
    otp: str = Form(...),
    db: Session = Depends(db_session),
):
    verification = registration_verification_for_token(verification_token, db, lock=True)
    now = datetime.now(timezone.utc)
    if not verification or datetime.fromisoformat(verification.expires_at) <= now:
        return templates.TemplateResponse("auth.html", registration_otp_context(
            request, verification, verification_token, db,
            "Mã OTP không hợp lệ hoặc đã hết hạn. Hãy quay lại link mời để đăng ký lại.",
        ), status_code=400)
    if verification.attempt_count >= REGISTRATION_OTP_MAX_ATTEMPTS:
        return templates.TemplateResponse("auth.html", registration_otp_context(
            request, verification, verification_token, db,
            "Bạn đã nhập sai quá số lần cho phép. Hãy gửi lại mã OTP mới.",
        ), status_code=429)
    normalized_otp = otp.strip()
    if not normalized_otp.isdigit() or len(normalized_otp) != 6 or not hmac.compare_digest(
        verification.otp_hash,
        registration_otp_hash(verification.email, normalized_otp),
    ):
        verification.attempt_count += 1
        remaining = max(0, REGISTRATION_OTP_MAX_ATTEMPTS - verification.attempt_count)
        db.commit()
        return templates.TemplateResponse("auth.html", registration_otp_context(
            request, verification, verification_token, db,
            f"Mã OTP không đúng. Bạn còn {remaining} lần thử.",
        ), status_code=400)

    teacher = db.scalar(select(Teacher).where(
        Teacher.id == verification.teacher_id,
        Teacher.project_id == verification.project_id,
    ).with_for_update())
    if not teacher or account_for_teacher(verification.teacher_id, db):
        return templates.TemplateResponse("auth.html", registration_otp_context(
            request, verification, verification_token, db,
            "Hồ sơ giáo viên đã được liên kết với tài khoản khác. Hãy liên hệ quản trị viên.",
        ), status_code=409)
    if db.scalar(select(User.id).where(User.email == verification.email)) is not None:
        return templates.TemplateResponse("auth.html", registration_otp_context(
            request, verification, verification_token, db,
            "Email này đã được đăng ký. Hãy chuyển sang trang đăng nhập.",
        ), status_code=409)

    user = User(
        name=verification.name,
        email=verification.email,
        password_hash=verification.password_hash,
        role="teacher",
        teacher_id=teacher.id,
    )
    db.add(user)
    try:
        db.flush()
        ensure_teacher_link(user, teacher, db)
        db.delete(verification)
        db.commit()
    except IntegrityError:
        db.rollback()
        return templates.TemplateResponse("auth.html", registration_otp_context(
            request, None, verification_token, db,
            "Email hoặc hồ sơ giáo viên vừa được đăng ký ở một phiên khác. Hãy đăng nhập hoặc liên hệ quản trị viên.",
        ), status_code=409)
    response = RedirectResponse(f"/teacher?project_id={teacher.project_id}", 303)
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
    verification = registration_verification_for_token(verification_token, db, lock=True)
    if not verification:
        return templates.TemplateResponse("auth.html", registration_otp_context(
            request, None, verification_token, db,
            "Phiên xác minh không còn hợp lệ. Hãy đăng ký lại từ link mời.",
        ), status_code=400)
    if website.strip() or human_confirm != "yes" or not captcha_is_valid(captcha_token, captcha_answer, "registration_resend"):
        return templates.TemplateResponse("auth.html", registration_otp_context(
            request, verification, verification_token, db,
            "Xác minh bảo mật không đúng hoặc thao tác quá nhanh.",
        ), status_code=400)
    now = datetime.now(timezone.utc)
    if datetime.fromisoformat(verification.resend_available_at) > now:
        return templates.TemplateResponse("auth.html", registration_otp_context(
            request, verification, verification_token, db,
            "Vui lòng chờ đủ 60 giây trước khi yêu cầu mã mới.",
        ), status_code=429)
    project = db.get(Project, verification.project_id)
    otp = f"{secrets.randbelow(1_000_000):06d}"
    try:
        if not send_registration_otp_email(
            verification.email,
            otp,
            project.name if project else "Smart TKB",
        ):
            raise RuntimeError("SMTP chưa được cấu hình")
    except (OSError, smtplib.SMTPException, RuntimeError, ValueError) as exc:
        logger.exception("Could not resend registration OTP to %s: %s", verification.email, exc)
        return templates.TemplateResponse("auth.html", registration_otp_context(
            request, verification, verification_token, db,
            "Chưa thể gửi lại mã OTP. Vui lòng thử lại sau.",
        ), status_code=503)
    verification.otp_hash = registration_otp_hash(verification.email, otp)
    nonce = secrets.token_urlsafe(32)
    verification.token_hash = hashlib.sha256(nonce.encode()).hexdigest()
    verification.expires_at = (now + timedelta(seconds=REGISTRATION_OTP_TTL_SECONDS)).isoformat()
    verification.resend_available_at = (now + timedelta(seconds=REGISTRATION_OTP_RESEND_SECONDS)).isoformat()
    verification.attempt_count = 0
    db.commit()
    refreshed_token = registration_signer.dumps({"id": verification.id, "nonce": nonce})
    return templates.TemplateResponse("auth.html", registration_otp_context(
        request, verification, refreshed_token, db,
    ))

@app.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request):
    question, captcha_token = new_captcha()
    return templates.TemplateResponse("forgot_password.html", {
        "request": request,
        "question": question,
        "captcha_token": captcha_token,
        "error": None,
        "submitted": False,
        "dev_reset_link": None,
    })

@app.post("/forgot-password", response_class=HTMLResponse)
def forgot_password(
    request: Request,
    email: str = Form(...),
    not_robot: Optional[str] = Form(None),
    captcha_answer: str = Form(...),
    captcha_token: str = Form(...),
    db: Session = Depends(db_session),
):
    if not_robot != "yes" or not captcha_is_valid(captcha_token, captcha_answer):
        question, fresh_token = new_captcha()
        return templates.TemplateResponse("forgot_password.html", {
            "request": request,
            "question": question,
            "captcha_token": fresh_token,
            "error": "Xác minh Tôi không phải robot chưa đúng. Vui lòng thử lại.",
            "submitted": False,
            "dev_reset_link": None,
        }, status_code=400)

    account = db.scalar(select(User).where(User.email == email.lower().strip()))
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
                    logger.info("Password-reset email accepted by SMTP for %s", account.email)
            except (OSError, smtplib.SMTPException, ValueError) as exc:
                email_sent = False
                logger.exception("Could not send password-reset email to %s: %s", account.email, exc)
        if allow_local_link and not email_sent:
            dev_reset_link = reset_url
    elif account and smtp_configured and not base_url:
        logger.error("Password reset skipped because APP_BASE_URL is not configured")

    question, fresh_token = new_captcha()
    return templates.TemplateResponse("forgot_password.html", {
        "request": request,
        "question": question,
        "captcha_token": fresh_token,
        "error": None,
        "submitted": True,
        "dev_reset_link": dev_reset_link,
    })

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
def reset_password_page(token: str, request: Request, db: Session = Depends(db_session)):
    account = reset_account_for_token(token, db)
    return templates.TemplateResponse("reset_password.html", {
        "request": request,
        "token": token,
        "valid": account is not None,
        "error": None,
        "success": False,
    }, status_code=200 if account else 400)

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
        error = "Liên kết đặt lại mật khẩu không hợp lệ, đã hết hạn hoặc đã được sử dụng."
    elif len(password) < MIN_PASSWORD_LENGTH:
        error = f"Mật khẩu mới phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự."
    elif password != password_confirm:
        error = "Hai lần nhập mật khẩu không khớp."
    if error:
        return templates.TemplateResponse("reset_password.html", {
            "request": request,
            "token": token,
            "valid": account is not None,
            "error": error,
            "success": False,
        }, status_code=400)

    account.password_hash = pwd.hash(password)
    account.session_version += 1
    account.reset_token_hash = None
    account.reset_token_expires_at = None
    db.commit()
    return templates.TemplateResponse("reset_password.html", {
        "request": request,
        "token": token,
        "valid": False,
        "error": None,
        "success": True,
    })

@app.get("/logout")
def logout():
    res = RedirectResponse("/", 303); res.delete_cookie("session"); return res

@app.get("/account-pending", response_class=HTMLResponse)
def account_pending(request: Request, user: User = Depends(current_user)):
    if is_admin(user):
        return RedirectResponse("/projects", 303)
    if user.role == "teacher":
        return RedirectResponse("/teacher", 303)
    return templates.TemplateResponse("user_pending.html", {"request": request, "user": user})

@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request, user: User = Depends(current_user), db: Session = Depends(db_session)):
    if not is_admin(user):
        raise HTTPException(403, "Chỉ quản trị viên được quản lý tài khoản")
    project_query = select(Project)
    if not is_super_admin(user):
        project_query = project_query.where(Project.owner_id == user.id)
    projects = db.scalars(project_query.order_by(Project.id.asc())).all()
    project_names = {project.id: project.name for project in projects}
    project_ids = set(project_names)
    managed_teacher_ids = admin_teacher_ids(user, db)
    all_users = db.scalars(select(User).order_by(User.id.asc())).all()
    users = [account for account in all_users if admin_can_manage_account(user, account, db)]
    assigned_teacher_ids = set(db.scalars(select(TeacherAccountLink.teacher_id)).all())
    assigned_teacher_ids.update(db.scalars(
        select(User.teacher_id).where(User.role == "teacher", User.teacher_id.is_not(None))
    ).all())
    managed_account_ids = {account.id for account in users if account.role == "teacher" and admin_can_manage_account(user, account, db)}
    available_teachers = []
    if project_ids:
        teachers = db.scalars(
            select(Teacher).where(Teacher.project_id.in_(project_ids)).order_by(Teacher.name.asc())
        ).all()
        available_teachers = [
            {
                "id": teacher.id,
                "name": teacher.name,
                "project_id": teacher.project_id,
                "project_name": project_names[teacher.project_id],
            }
            for teacher in teachers
            if teacher.id not in assigned_teacher_ids
        ]
    chatbot_error_logs = []
    chatbot_error_log_count = 0
    if is_super_admin(user):
        chatbot_error_log_count = db.scalar(select(func.count(ChatbotErrorLog.id))) or 0
        chatbot_error_logs = db.scalars(
            select(ChatbotErrorLog)
            .order_by(ChatbotErrorLog.id.desc())
            .limit(100)
        ).all()
    return templates.TemplateResponse("users.html", {
        "request": request,
        "user": user,
        "users": users,
        "available_teachers": available_teachers,
        "managed_projects": projects,
        "managed_teacher_ids": managed_teacher_ids,
        "managed_account_ids": managed_account_ids,
        "project_names": project_names,
        "chatbot_error_logs": chatbot_error_logs,
        "chatbot_error_log_count": chatbot_error_log_count,
    })

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
    name: str = Form(...),
    email: str = Form(...),
    requested_teacher_name: str = Form(""),
    password: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_admin(user):
        raise HTTPException(403, "Chỉ quản trị viên được quản lý tài khoản")
    account = db.get(User, account_id)
    if not account or not admin_can_manage_account(user, account, db):
        raise HTTPException(404, "Không tìm thấy tài khoản trong phạm vi quản lý")
    name = bounded_text(name, "Họ tên", 120)
    email = bounded_text(email.lower(), "Email", 255)
    requested_teacher_name = bounded_text(
        requested_teacher_name, "Tên giáo viên mong muốn", 120, required=False
    )
    if "@" not in email:
        raise HTTPException(400, "Email không hợp lệ")
    conflict = db.scalar(select(User).where(User.email == email, User.id != account.id))
    if conflict:
        raise HTTPException(409, "Email đã được dùng cho tài khoản khác")
    account.name = name
    account.email = email
    account.requested_teacher_name = requested_teacher_name or None
    password_changed = bool(password.strip())
    if password_changed:
        if len(password.strip()) < MIN_PASSWORD_LENGTH:
            raise HTTPException(400, f"Mật khẩu mới phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự")
        account.password_hash = pwd.hash(password.strip())
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
        raise HTTPException(400, "Không thể xóa tài khoản đang sở hữu bộ thời khóa biểu")
    for link in db.scalars(select(TeacherAccountLink).where(TeacherAccountLink.user_id == account.id)).all():
        db.delete(link)
    db.flush()
    db.delete(account)
    db.commit()
    return RedirectResponse("/admin/users", 303)

@app.post("/admin/users/{account_id}/approve")
def approve_teacher_account(
    account_id: int,
    teacher_id: str = Form(""),
    project_id: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_admin(user):
        raise HTTPException(403, "Chỉ quản trị viên được quản lý tài khoản")
    account = db.get(User, account_id)
    if not account or not admin_can_manage_account(user, account, db):
        raise HTTPException(404, "Không tìm thấy tài khoản trong phạm vi quản lý")
    if account.role != "pending":
        raise HTTPException(400, "Chỉ có thể duyệt tài khoản đang chờ")
    teacher_id = teacher_id.strip()
    project_id = project_id.strip()
    if teacher_id and not teacher_id.isdigit():
        raise HTTPException(400, "Giáo viên được chọn không hợp lệ")
    if project_id and not project_id.isdigit():
        raise HTTPException(400, "Bộ thời khóa biểu được chọn không hợp lệ")
    selected_teacher_id = int(teacher_id) if teacher_id else None
    selected_project_id = int(project_id) if project_id else None
    if selected_teacher_id is not None:
        teacher = db.get(Teacher, selected_teacher_id)
        project = db.get(Project, teacher.project_id) if teacher else None
        if not teacher or not project or (not is_super_admin(user) and project.owner_id != user.id):
            raise HTTPException(400, "Giáo viên không hợp lệ hoặc không thuộc bộ thời khóa biểu của bạn")
        if account.requested_project_id is not None and project.id != account.requested_project_id:
            raise HTTPException(403, "Tài khoản này được mời vào một bộ thời khóa biểu khác")
        if account_for_teacher(teacher.id, db):
            raise HTTPException(400, "Giáo viên này đã có tài khoản")
    else:
        teacher_name = (account.requested_teacher_name or "").strip()
        if not teacher_name:
            raise HTTPException(400, "Hãy nhập tên giáo viên mong muốn hoặc chọn một giáo viên có sẵn")
        managed_project_query = select(Project)
        if not is_super_admin(user):
            managed_project_query = managed_project_query.where(Project.owner_id == user.id)
        managed_projects = db.scalars(managed_project_query.order_by(Project.id.asc())).all()
        if selected_project_id is None and len(managed_projects) == 1:
            project = managed_projects[0]
        else:
            project = db.get(Project, selected_project_id) if selected_project_id is not None else None
        if not project or (not is_super_admin(user) and project.owner_id != user.id):
            raise HTTPException(400, "Hãy chọn bộ thời khóa biểu để tạo hồ sơ giáo viên mới")
        if account.requested_project_id is not None and project.id != account.requested_project_id:
            raise HTTPException(403, "Tài khoản này được mời vào một bộ thời khóa biểu khác")
        short_name = teacher_name.split()[-1][:30]
        teacher = Teacher(
            project_id=project.id,
            name=teacher_name,
            short_name=short_name,
            max_periods_day=5,
        )
        db.add(teacher)
        db.flush()
    account.role = "teacher"
    account.teacher_id = teacher.id
    ensure_teacher_link(account, teacher, db)
    account.requested_project_id = None
    db.commit()
    return RedirectResponse("/admin/users", 303)

@app.post("/admin/users/{account_id}/promote-admin")
def promote_teacher_to_admin(
    account_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_admin(user):
        raise HTTPException(403, "Chỉ quản trị viên được quản lý tài khoản")
    account = db.get(User, account_id)
    if not account:
        raise HTTPException(404, "Không tìm thấy tài khoản")
    if account.role != "teacher":
        raise HTTPException(400, "Chỉ có thể nâng tài khoản giáo viên lên quản trị viên")
    if not admin_can_manage_account(user, account, db):
        raise HTTPException(403, "Bạn không quản lý tài khoản giáo viên này")
    for link in db.scalars(select(TeacherAccountLink).where(TeacherAccountLink.user_id == account.id)).all():
        db.delete(link)
    clear_teacher_identity(account)
    account.role = "admin"
    # Thay đổi quyền phải vô hiệu toàn bộ cookie phiên cũ của tài khoản giáo viên.
    account.session_version += 1
    db.commit()
    return RedirectResponse("/admin/users", 303)

@app.get("/projects", response_class=HTMLResponse)
def projects(request: Request, user: User = Depends(current_user), db: Session = Depends(db_session)):
    if user.role == "teacher":
        return RedirectResponse("/teacher", 303)
    if not is_admin(user):
        return RedirectResponse("/account-pending", 303)
    project_query = select(Project)
    if not is_super_admin(user):
        project_query = project_query.where(Project.owner_id == user.id)
    rows = db.scalars(project_query.order_by(Project.id.desc())).all()
    return templates.TemplateResponse("projects.html", {"request": request, "user": user, "projects": rows})

@app.post("/projects")
def create_project(name: str = Form(...), school_name: str = Form(...), days: int = Form(6), sessions: int = Form(2), periods: int = Form(5), user: User = Depends(current_user), db: Session = Depends(db_session)):
    if not is_admin(user): raise HTTPException(403)
    clean_name=name.strip(); clean_school_name=school_name.strip()
    if not clean_name: raise HTTPException(400,"Tên bộ thời khóa biểu không được để trống")
    if not clean_school_name: raise HTTPException(400,"Tên trường không được để trống")
    if len(clean_name)>200: raise HTTPException(400,"Tên bộ thời khóa biểu không được vượt quá 200 ký tự")
    if len(clean_school_name)>200: raise HTTPException(400,"Tên trường không được vượt quá 200 ký tự")
    validated_days=bounded_int(days,6,1,7,"Số ngày học")
    validated_sessions=bounded_int(sessions,2,1,2,"Số buổi mỗi ngày")
    validated_periods=bounded_int(periods,5,1,8,"Số tiết mỗi buổi")
    p = Project(owner_id=user.id, name=clean_name, school_name=clean_school_name, days=validated_days, sessions=validated_sessions, periods_per_session=validated_periods)
    db.add(p); db.commit()
    return RedirectResponse(f"/projects/{p.id}", 303)

@app.post("/projects/{pid}/clone")
def clone_project(pid: int, user: User = Depends(current_user), db: Session = Depends(db_session)):
    # Dùng cùng khóa với mọi API chỉnh sửa để bản sao luôn được đọc từ một
    # trạng thái nhất quán, không trộn dữ liệu trước và sau một thay đổi đồng thời.
    src = get_project_for_update(pid,user,db)
    suffix = " (bản sao)"
    clone_name = src.name[: 200 - len(suffix)] + suffix
    p = Project(owner_id=user.id,name=clone_name,school_name=src.school_name,days=src.days,sessions=src.sessions,periods_per_session=src.periods_per_session,blocked_slots_json=src.blocked_slots_json)
    db.add(p); db.flush()
    maps = {"dep":{},"sub":{},"tea":{},"grade":{},"cls":{},"ass":{}}
    for x in db.scalars(select(Department).where(Department.project_id==pid)):
        n=Department(project_id=p.id,name=x.name);db.add(n);db.flush();maps["dep"][x.id]=n.id
    for x in db.scalars(select(Subject).where(Subject.project_id==pid)):
        n=Subject(project_id=p.id,name=x.name,short_name=x.short_name,max_consecutive=x.max_consecutive);db.add(n);db.flush();maps["sub"][x.id]=n.id
    for x in db.scalars(select(Teacher).where(Teacher.project_id==pid)):
        n=Teacher(project_id=p.id,department_id=maps["dep"].get(x.department_id),name=x.name,short_name=x.short_name,max_periods_day=x.max_periods_day,unavailable_json=x.unavailable_json);db.add(n);db.flush();maps["tea"][x.id]=n.id
    # Bản sao chỉ sao chép dữ liệu chuyên môn. Quyền tài khoản giáo viên không
    # được kế thừa tự động để tránh cấp quyền ngoài ý muốn cho project mới.
    for x in db.scalars(select(TeacherSubject).where(TeacherSubject.project_id==pid)):
        if x.teacher_id in maps["tea"] and x.subject_id in maps["sub"]:
            db.add(TeacherSubject(project_id=p.id,teacher_id=maps["tea"][x.teacher_id],subject_id=maps["sub"][x.subject_id]))
    # Chỉ sao chép nguyện vọng đang được áp dụng vì đây là ràng buộc hiện hành
    # của lịch. Lịch sử pending/rejected/superseded vẫn thuộc project gốc.
    for x in db.scalars(select(TeacherPreference).where(
        TeacherPreference.project_id==pid,
        TeacherPreference.status=="accepted",
    )):
        if x.teacher_id in maps["tea"]:
            db.add(TeacherPreference(
                project_id=p.id,
                teacher_id=maps["tea"][x.teacher_id],
                preferred_json=x.preferred_json,
                unavailable_json=x.unavailable_json,
                note=x.note,
                status="accepted",
                created_at=x.created_at,
                reviewed_at=x.reviewed_at,
            ))
    for x in db.scalars(select(Grade).where(Grade.project_id==pid)):
        n=Grade(project_id=p.id,name=x.name);db.add(n);db.flush();maps["grade"][x.id]=n.id
    for x in db.scalars(select(GradeSubjectRequirement).where(GradeSubjectRequirement.project_id==pid)):
        if x.grade_id in maps["grade"] and x.subject_id in maps["sub"]:
            db.add(GradeSubjectRequirement(
                project_id=p.id, grade_id=maps["grade"][x.grade_id],
                subject_id=maps["sub"][x.subject_id], periods_per_week=x.periods_per_week,
                block_mode=x.block_mode,
            ))
    for x in db.scalars(select(SchoolClass).where(SchoolClass.project_id==pid)):
        n=SchoolClass(project_id=p.id,grade_id=maps["grade"].get(x.grade_id),name=x.name,unavailable_json=x.unavailable_json);db.add(n);db.flush();maps["cls"][x.id]=n.id
    for x in db.scalars(select(Assignment).where(Assignment.project_id==pid)):
        n=Assignment(project_id=p.id,class_id=maps["cls"][x.class_id],subject_id=maps["sub"][x.subject_id],teacher_id=maps["tea"][x.teacher_id],periods_per_week=x.periods_per_week,block_mode=x.block_mode,consecutive_pattern="");db.add(n);db.flush();maps["ass"][x.id]=n.id
    for x in db.scalars(select(FixedLesson).where(FixedLesson.project_id==pid)):
        if x.assignment_id in maps["ass"]:
            db.add(FixedLesson(project_id=p.id,assignment_id=maps["ass"][x.assignment_id],slot=x.slot,group_size=x.group_size))
    for x in db.scalars(select(Lesson).where(Lesson.project_id==pid)):
        db.add(Lesson(project_id=p.id,assignment_id=maps["ass"][x.assignment_id],slot=x.slot,locked=x.locked))
    db.commit(); return RedirectResponse(f"/projects/{p.id}",303)

@app.get("/schedule-audit", response_class=HTMLResponse)
def standalone_schedule_audit_page(request:Request, user:User=Depends(current_user)):
    return templates.TemplateResponse("schedule_audit.html", {
        "request":request,
        "user":user,
        "days":DAYS,
    })

@app.get("/projects/{pid}/schedule-audit")
def legacy_schedule_audit_page(pid:int, user:User=Depends(current_user)):
    # Route cu chi de bookmark cu khong bi loi; khong doc bat ky du lieu project nao.
    return RedirectResponse("/schedule-audit",303)

@app.get("/projects/{pid}", response_class=HTMLResponse)
def project_page(pid:int, request:Request, user:User=Depends(current_user), db:Session=Depends(db_session)):
    p=get_project(pid,user,db)
    data=project_data(db,p)
    return templates.TemplateResponse("workspace.html", {
        "request":request,
        "user":user,
        "p":p,
        "data":data,
        "days":DAYS,
        "chatbot_enabled":bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "chatbot_primary_model":os.getenv("GEMINI_MODEL", "gemini-3.7-flash").strip() or "gemini-3.7-flash",
    })

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

@app.post("/api/schedule-audit")
def standalone_audit_schedule_file(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
):
    filename, content = read_schedule_upload(file)
    from app.schedule_audit import ScheduleAuditParseError, analyze_standalone_schedule_file
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
            {"ok": False, "message": "Không thể phân tích file thời khóa biểu này. Hãy kiểm tra lại cấu trúc file."},
            status_code=500,
        )

@app.post("/api/schedule-import/convert")
def standalone_convert_schedule_file_to_draft(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
):
    filename, content = read_schedule_upload(file)
    from app.schedule_audit import ScheduleAuditParseError, analyze_standalone_schedule_file
    try:
        report = analyze_standalone_schedule_file(
            filename=filename,
            content=content,
            include_editable=True,
        )
    except ScheduleAuditParseError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
    except Exception:
        logger.exception("standalone schedule import conversion failed")
        return JSONResponse(
            {"ok": False, "message": "Không thể chuyển file thành bản nháp chỉnh sửa."},
            status_code=500,
        )
    editable = report.pop("editable_lessons", [])
    data = report.get("data") or {}
    if not editable:
        return JSONResponse(
            {"ok": False, "message": "Không có tiết nào đủ thông tin để chuyển sang chỉnh sửa kéo-thả."},
            status_code=400,
        )
    stem = os.path.splitext(os.path.basename(filename))[0].strip() or "TKB import"
    return {
        "ok": True,
        "filename": filename,
        "suggested_name": stem[:200],
        "suggested_school_name": "Trường học",
        "lessons": editable,
        "data": data,
        "audit": report,
    }

def audit_schedule_file(
    pid: int,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    p = get_project(pid, user, db)
    filename, content = read_schedule_upload(file)

    from app.schedule_audit import ScheduleAuditParseError, analyze_schedule_file

    data = project_data(db, p)
    try:
        return analyze_schedule_file(
            filename=filename,
            content=content,
            project=data["project"],
            classes=data["classes"],
            subjects=data["subjects"],
            teachers=data["teachers"],
            assignments=data["assignments"],
        )
    except ScheduleAuditParseError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
    except Exception:
        logger.exception("schedule audit failed for project %s", pid)
        return JSONResponse(
            {"ok": False, "message": "Không thể phân tích file thời khóa biểu này. Hãy kiểm tra lại cấu trúc file."},
            status_code=500,
        )

class ImportedDraftLessonIn(BaseModel):
    draft_id: int = Field(ge=1)
    assignment_id: int = Field(ge=1)
    slot: int = Field(ge=0)

class ImportedScheduleEditIn(BaseModel):
    action: str
    lessons: list[ImportedDraftLessonIn]
    draft_id: Optional[int] = None
    assignment_id: Optional[int] = None
    slot: Optional[int] = None

class ImportedScheduleSaveIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    lessons: list[ImportedDraftLessonIn]

class StandaloneImportedScheduleEditIn(BaseModel):
    action: str
    data: dict
    lessons: list[ImportedDraftLessonIn]
    draft_id: Optional[int] = None
    assignment_id: Optional[int] = None
    slot: Optional[int] = None

class StandaloneImportedScheduleSaveIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    school_name: str = Field(default="Trường học", max_length=200)
    data: dict
    lessons: list[ImportedDraftLessonIn]

def normalize_standalone_import_data(raw_data: dict) -> dict:
    if not isinstance(raw_data, dict):
        raise HTTPException(400, "Dữ liệu bản nháp import không hợp lệ.")
    raw_project = raw_data.get("project")
    if not isinstance(raw_project, dict):
        raise HTTPException(400, "Bản nháp thiếu cấu trúc thời khóa biểu.")
    project = {
        "id": 0,
        "name": "TKB import",
        "school_name": "Trường học",
        "days": bounded_int(raw_project.get("days"), 6, 1, 7, "Số ngày học"),
        "sessions": bounded_int(raw_project.get("sessions"), 1, 1, 2, "Số buổi mỗi ngày"),
        "periods": bounded_int(raw_project.get("periods"), 5, 1, 8, "Số tiết mỗi buổi"),
        "blocked_slots": [],
    }

    def rows_of(name: str, maximum: int) -> list[dict]:
        rows = raw_data.get(name)
        if not isinstance(rows, list) or len(rows) > maximum:
            raise HTTPException(400, f"Dữ liệu {name} của bản nháp không hợp lệ.")
        if any(not isinstance(item, dict) for item in rows):
            raise HTTPException(400, f"Dữ liệu {name} của bản nháp không hợp lệ.")
        return rows

    class_rows = rows_of("classes", 2000)
    subject_rows = rows_of("subjects", 1000)
    teacher_rows = rows_of("teachers", 2000)
    assignment_rows = rows_of("assignments", 10000)

    classes = []
    class_ids = set()
    for row in class_rows:
        item_id = bounded_int(row.get("id"), 0, 1, 1_000_000, "Mã lớp")
        name = str(row.get("name") or "").strip()
        if not name or len(name) > 80 or item_id in class_ids:
            raise HTTPException(400, "Danh sách lớp của bản nháp không hợp lệ.")
        class_ids.add(item_id)
        classes.append({"id": item_id, "name": name, "grade_id": None, "unavailable": []})

    subjects = []
    subject_ids = set()
    for row in subject_rows:
        item_id = bounded_int(row.get("id"), 0, 1, 1_000_000, "Mã môn")
        name = str(row.get("name") or "").strip()
        short_name = str(row.get("short_name") or name).strip()[:20]
        if not name or len(name) > 120 or item_id in subject_ids:
            raise HTTPException(400, "Danh sách môn học của bản nháp không hợp lệ.")
        subject_ids.add(item_id)
        subjects.append({
            "id": item_id, "name": name, "short_name": short_name or f"M{item_id}",
            "max_consecutive": bounded_int(row.get("max_consecutive"), project["periods"], 1, 8, "Số tiết liên tiếp"),
        })

    teachers = []
    teacher_ids = set()
    for row in teacher_rows:
        item_id = bounded_int(row.get("id"), 0, 1, 1_000_000, "Mã giáo viên")
        name = str(row.get("name") or "").strip()
        short_name = str(row.get("short_name") or name).strip()[:30]
        if not name or len(name) > 120 or item_id in teacher_ids:
            raise HTTPException(400, "Danh sách giáo viên của bản nháp không hợp lệ.")
        teacher_ids.add(item_id)
        teachers.append({
            "id": item_id, "name": name, "short_name": short_name or f"GV{item_id}",
            "department_id": None,
            "max_periods_day": bounded_int(
                row.get("max_periods_day"),
                project["sessions"] * project["periods"],
                1,
                project["sessions"] * project["periods"],
                "Số tiết tối đa/ngày",
            ),
            "unavailable": [],
            "subject_ids": [],
        })

    classes_by_id = {row["id"]: row for row in classes}
    subjects_by_id = {row["id"]: row for row in subjects}
    teachers_by_id = {row["id"]: row for row in teachers}
    assignments = []
    assignment_ids = set()
    assignment_pairs = set()
    teacher_subjects = defaultdict(set)
    for row in assignment_rows:
        item_id = bounded_int(row.get("id"), 0, 1, 10_000_000, "Mã phân công")
        class_id = bounded_int(row.get("class_id"), 0, 1, 1_000_000, "Mã lớp")
        subject_id = bounded_int(row.get("subject_id"), 0, 1, 1_000_000, "Mã môn")
        teacher_id = bounded_int(row.get("teacher_id"), 0, 1, 1_000_000, "Mã giáo viên")
        if item_id in assignment_ids or class_id not in classes_by_id or subject_id not in subjects_by_id or teacher_id not in teachers_by_id:
            raise HTTPException(400, "Danh sách phân công của bản nháp không hợp lệ.")
        pair = (class_id, subject_id)
        if pair in assignment_pairs:
            raise HTTPException(400, "File có nhiều giáo viên cho cùng một lớp/môn; cấu trúc này chưa thể lưu thành TKB mới.")
        assignment_ids.add(item_id)
        assignment_pairs.add(pair)
        teacher_subjects[teacher_id].add(subject_id)
        assignments.append({
            "id": item_id,
            "class_id": class_id,
            "subject_id": subject_id,
            "teacher_id": teacher_id,
            "periods_per_week": bounded_int(row.get("periods_per_week"), 1, 1, 100, "Số tiết/tuần"),
            "block_mode": "free",
            "class_name": classes_by_id[class_id]["name"],
            "subject_name": subjects_by_id[subject_id]["name"],
            "subject_short": subjects_by_id[subject_id]["short_name"],
            "teacher_name": teachers_by_id[teacher_id]["name"],
            "teacher_short": teachers_by_id[teacher_id]["short_name"],
        })
    for teacher in teachers:
        teacher["subject_ids"] = sorted(teacher_subjects.get(teacher["id"], set()))
    return {
        "project": project,
        "classes": classes,
        "subjects": subjects,
        "teachers": teachers,
        "assignments": assignments,
        "lessons": [],
    }

def normalize_standalone_draft_lessons(
    data: dict,
    lessons: list[ImportedDraftLessonIn],
) -> tuple[list[dict[str, int]], dict[int, dict]]:
    if len(lessons) > 10_000:
        raise HTTPException(400, "Bản nháp có quá nhiều tiết để xử lý.")
    assignments = {int(item["id"]): item for item in data["assignments"]}
    normalized = []
    seen_draft_ids = set()
    project = data["project"]
    maximum = int(project["days"]) * int(project["sessions"]) * int(project["periods"])
    for item in lessons:
        if item.draft_id in seen_draft_ids:
            raise HTTPException(400, "Bản nháp có mã tiết bị trùng.")
        if item.assignment_id not in assignments:
            raise HTTPException(400, "Bản nháp chứa phân công không hợp lệ.")
        if item.slot < 0 or item.slot >= maximum:
            raise HTTPException(400, "Bản nháp chứa ô thời khóa biểu không hợp lệ.")
        seen_draft_ids.add(item.draft_id)
        normalized.append({
            "draft_id": int(item.draft_id),
            "assignment_id": int(item.assignment_id),
            "slot": int(item.slot),
        })
    return normalized, assignments

def standalone_draft_target_error(
    data: dict,
    assignment: dict,
    slot: int,
    lessons: list[dict[str, int]],
    assignments: dict[int, dict],
    *,
    exclude_draft_id: Optional[int] = None,
) -> Optional[str]:
    project = data["project"]
    maximum = int(project["days"]) * int(project["sessions"]) * int(project["periods"])
    if slot < 0 or slot >= maximum:
        return "Ô thời khóa biểu không hợp lệ."
    peers = [item for item in lessons if item["draft_id"] != exclude_draft_id]
    for item in peers:
        if item["slot"] != slot:
            continue
        other = assignments.get(item["assignment_id"])
        if other and (other["class_id"] == assignment["class_id"] or other["teacher_id"] == assignment["teacher_id"]):
            return "Ô đích bị trùng lớp hoặc giáo viên."

    teachers = {int(item["id"]): item for item in data["teachers"]}
    subjects = {int(item["id"]): item for item in data["subjects"]}
    teacher = teachers.get(int(assignment["teacher_id"]))
    subject = subjects.get(int(assignment["subject_id"]))
    ppd = int(project["sessions"]) * int(project["periods"])
    day = slot // ppd
    inside = slot % ppd
    session = inside // int(project["periods"])
    period = inside % int(project["periods"])
    if teacher:
        teacher_periods = sum(
            1 for item in peers
            if item["slot"] // ppd == day
            and assignments[item["assignment_id"]]["teacher_id"] == assignment["teacher_id"]
        )
        if teacher_periods >= int(teacher["max_periods_day"]):
            return "Giáo viên đã đạt số tiết tối đa trong ngày của bản import."
    if subject:
        same_subject_periods = []
        for item in peers:
            if item["slot"] // ppd != day:
                continue
            other = assignments[item["assignment_id"]]
            other_inside = item["slot"] % ppd
            if (
                other_inside // int(project["periods"]) == session
                and other["class_id"] == assignment["class_id"]
                and other["subject_id"] == assignment["subject_id"]
            ):
                same_subject_periods.append(other_inside % int(project["periods"]))
        run = sorted(set(same_subject_periods + [period]))
        longest = current = 1
        for left, right in zip(run, run[1:]):
            current = current + 1 if right == left + 1 else 1
            longest = max(longest, current)
        if longest > int(subject["max_consecutive"]):
            return "Vượt số tiết liên tiếp tối đa của môn học trong bản import."
    return None

def standalone_draft_validation_error(
    data: dict,
    lessons: list[dict[str, int]],
    assignments: dict[int, dict],
) -> Optional[str]:
    counts = Counter(item["assignment_id"] for item in lessons)
    for assignment_id, count in counts.items():
        if count > int(assignments[assignment_id]["periods_per_week"]):
            return "Có phân công đang vượt số tiết gốc trong file import."
    for item in lessons:
        assignment = assignments[item["assignment_id"]]
        error = standalone_draft_target_error(
            data, assignment, item["slot"], lessons, assignments,
            exclude_draft_id=item["draft_id"],
        )
        if error:
            return error
    return None

@app.post("/api/schedule-import/edit")
def standalone_edit_imported_schedule_draft(
    payload: StandaloneImportedScheduleEditIn,
    user: User = Depends(current_user),
):
    data = normalize_standalone_import_data(payload.data)
    lessons, assignments = normalize_standalone_draft_lessons(data, payload.lessons)
    action = payload.action.strip().lower()
    if action not in {"move", "add", "remove"}:
        raise HTTPException(400, "Thao tác chỉnh sửa bản nháp không hợp lệ.")

    if action == "remove":
        if payload.draft_id is None:
            raise HTTPException(400, "Thiếu mã tiết cần gỡ.")
        updated = [item for item in lessons if item["draft_id"] != payload.draft_id]
        if len(updated) == len(lessons):
            raise HTTPException(404, "Không tìm thấy tiết cần gỡ trong bản nháp.")
        return {"ok": True, "lessons": updated, "message": "Đã đưa tiết về kho của bản nháp."}

    if payload.slot is None:
        raise HTTPException(400, "Thiếu ô đích của thời khóa biểu.")

    if action == "move":
        if payload.draft_id is None:
            raise HTTPException(400, "Thiếu mã tiết cần di chuyển.")
        lesson = next((item for item in lessons if item["draft_id"] == payload.draft_id), None)
        if lesson is None:
            raise HTTPException(404, "Không tìm thấy tiết cần di chuyển trong bản nháp.")
        assignment = assignments[lesson["assignment_id"]]
        error = standalone_draft_target_error(
            data, assignment, payload.slot, lessons, assignments,
            exclude_draft_id=lesson["draft_id"],
        )
        if error:
            return JSONResponse({"ok": False, "message": error}, status_code=409)
        updated = [dict(item) for item in lessons]
        for item in updated:
            if item["draft_id"] == lesson["draft_id"]:
                item["slot"] = int(payload.slot)
                break
        return {"ok": True, "lessons": updated, "message": "Đã di chuyển tiết trong bản nháp."}

    if payload.assignment_id is None:
        raise HTTPException(400, "Thiếu phân công cần thêm vào lịch.")
    assignment = assignments.get(payload.assignment_id)
    if assignment is None:
        raise HTTPException(404, "Phân công không tồn tại trong bản import.")
    scheduled = sum(1 for item in lessons if item["assignment_id"] == assignment["id"])
    if scheduled >= int(assignment["periods_per_week"]):
        return JSONResponse({"ok": False, "message": "Phân công này đã đủ số tiết theo file import."}, status_code=409)
    error = standalone_draft_target_error(data, assignment, payload.slot, lessons, assignments)
    if error:
        return JSONResponse({"ok": False, "message": error}, status_code=409)
    next_draft_id = max((item["draft_id"] for item in lessons), default=0) + 1
    updated = [*lessons, {"draft_id": next_draft_id, "assignment_id": assignment["id"], "slot": int(payload.slot)}]
    return {"ok": True, "lessons": updated, "message": "Đã thêm tiết vào bản nháp."}

def create_project_from_standalone_import(
    db: Session,
    owner_id: int,
    name: str,
    school_name: str,
    data: dict,
    lessons: list[dict[str, int]],
) -> Project:
    project_data = data["project"]
    project = Project(
        owner_id=owner_id,
        name=name,
        school_name=school_name,
        days=int(project_data["days"]),
        sessions=int(project_data["sessions"]),
        periods_per_session=int(project_data["periods"]),
        blocked_slots_json="[]",
    )
    db.add(project)
    db.flush()

    subject_map = {}
    for row in data["subjects"]:
        item = Subject(
            project_id=project.id,
            name=row["name"],
            short_name=row["short_name"],
            max_consecutive=int(row["max_consecutive"]),
        )
        db.add(item); db.flush(); subject_map[int(row["id"])] = item.id

    teacher_map = {}
    for row in data["teachers"]:
        item = Teacher(
            project_id=project.id,
            department_id=None,
            name=row["name"],
            short_name=row["short_name"],
            max_periods_day=int(row["max_periods_day"]),
            unavailable_json="[]",
        )
        db.add(item); db.flush(); teacher_map[int(row["id"])] = item.id

    class_map = {}
    for row in data["classes"]:
        item = SchoolClass(
            project_id=project.id,
            grade_id=None,
            name=row["name"],
            unavailable_json="[]",
        )
        db.add(item); db.flush(); class_map[int(row["id"])] = item.id

    assignment_map = {}
    teacher_subject_pairs = set()
    for row in data["assignments"]:
        item = Assignment(
            project_id=project.id,
            class_id=class_map[int(row["class_id"])],
            subject_id=subject_map[int(row["subject_id"])],
            teacher_id=teacher_map[int(row["teacher_id"])],
            periods_per_week=int(row["periods_per_week"]),
            block_mode="free",
            consecutive_pattern="",
        )
        db.add(item); db.flush(); assignment_map[int(row["id"])] = item.id
        teacher_subject_pairs.add((int(row["teacher_id"]), int(row["subject_id"])))

    for teacher_id, subject_id in teacher_subject_pairs:
        db.add(TeacherSubject(
            project_id=project.id,
            teacher_id=teacher_map[teacher_id],
            subject_id=subject_map[subject_id],
        ))

    for row in lessons:
        mapped_assignment = assignment_map.get(int(row["assignment_id"]))
        if mapped_assignment is None:
            raise HTTPException(400, "Không thể ánh xạ một phân công khi lưu TKB import.")
        db.add(Lesson(
            project_id=project.id,
            assignment_id=mapped_assignment,
            slot=int(row["slot"]),
            locked=False,
        ))
    return project

@app.post("/api/schedule-import/save")
def standalone_save_imported_schedule_as_project(
    payload: StandaloneImportedScheduleSaveIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    clean_name = payload.name.strip()
    clean_school_name = payload.school_name.strip() or "Trường học"
    if not clean_name:
        raise HTTPException(400, "Tên thời khóa biểu không được để trống.")
    if len(clean_school_name) > 200:
        raise HTTPException(400, "Tên trường không được vượt quá 200 ký tự.")
    data = normalize_standalone_import_data(payload.data)
    lessons, assignments = normalize_standalone_draft_lessons(data, payload.lessons)
    error = standalone_draft_validation_error(data, lessons, assignments)
    if error:
        return JSONResponse({"ok": False, "message": f"Chưa thể lưu: {error}"}, status_code=409)
    try:
        project = create_project_from_standalone_import(
            db, user.id, clean_name, clean_school_name, data, lessons,
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("standalone imported schedule save failed")
        raise
    return {
        "ok": True,
        "project_id": project.id,
        "dashboard_url": "/projects",
        "message": "Đã lưu file import thành một bộ thời khóa biểu mới độc lập trên Dashboard.",
    }

def normalize_import_draft_lessons(
    db: Session,
    project: Project,
    lessons: list[ImportedDraftLessonIn],
) -> tuple[list[dict[str, int]], dict[int, Assignment]]:
    if len(lessons) > 10_000:
        raise HTTPException(400, "Bản nháp có quá nhiều tiết để xử lý.")
    assignments = {
        assignment.id: assignment
        for assignment in db.scalars(select(Assignment).where(Assignment.project_id == project.id)).all()
    }
    normalized: list[dict[str, int]] = []
    seen_draft_ids: set[int] = set()
    maximum = project.days * project.sessions * project.periods_per_session
    for item in lessons:
        if item.draft_id in seen_draft_ids:
            raise HTTPException(400, "Bản nháp có mã tiết bị trùng.")
        seen_draft_ids.add(item.draft_id)
        if item.assignment_id not in assignments:
            raise HTTPException(400, "Bản nháp chứa phân công không còn tồn tại trong project.")
        if item.slot < 0 or item.slot >= maximum:
            raise HTTPException(400, "Bản nháp chứa ô thời khóa biểu không hợp lệ.")
        normalized.append({
            "draft_id": int(item.draft_id),
            "assignment_id": int(item.assignment_id),
            "slot": int(item.slot),
        })
    return normalized, assignments

def imported_draft_target_error(
    db: Session,
    project: Project,
    assignment: Assignment,
    slot: int,
    lessons: list[dict[str, int]],
    assignments: dict[int, Assignment],
    *,
    exclude_draft_id: Optional[int] = None,
    accepted_unavailable: Optional[dict[int, set[int]]] = None,
) -> Optional[str]:
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
    if accepted_unavailable is None:
        _, accepted_unavailable = accepted_teacher_preferences(db, project.id)
    if slot in accepted_unavailable.get(teacher.id, set()):
        return "Tiết này nằm trong nguyện vọng cần tránh đã được duyệt của giáo viên."
    if slot in parse_slots(school_class.unavailable_json):
        return "Lớp không học ở tiết này."

    peers = [item for item in lessons if item["draft_id"] != exclude_draft_id]
    for item in peers:
        if item["slot"] != slot:
            continue
        other = assignments.get(item["assignment_id"])
        if other and (other.class_id == assignment.class_id or other.teacher_id == assignment.teacher_id):
            return "Ô đích bị trùng lớp hoặc giáo viên."

    ppd = project.sessions * project.periods_per_session
    target_day = slot // ppd
    target_position = slot % ppd
    target_session = target_position // project.periods_per_session
    teacher_periods = 0
    subject_periods: list[int] = []
    for item in peers:
        other = assignments.get(item["assignment_id"])
        if not other or item["slot"] // ppd != target_day:
            continue
        if other.teacher_id == assignment.teacher_id:
            teacher_periods += 1
        position = item["slot"] % ppd
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

def imported_draft_pattern_error(
    project: Project,
    assignment: Assignment,
    lessons: list[dict[str, int]],
) -> Optional[str]:
    slots = [item["slot"] for item in lessons if item["assignment_id"] == assignment.id]
    if len(slots) > assignment.periods_per_week:
        return "Phân công này đã vượt số tiết/tuần."
    if not partial_assignment_pattern_matches(project, assignment, slots):
        return f"Vị trí này không thể hoàn thành hợp lệ theo chế độ {assignment_pattern_label(assignment)}."
    return None

def imported_draft_validation_error(
    db: Session,
    project: Project,
    lessons: list[dict[str, int]],
    assignments: dict[int, Assignment],
) -> Optional[str]:
    counts = Counter(item["assignment_id"] for item in lessons)
    _, accepted_unavailable = accepted_teacher_preferences(db, project.id)
    for assignment_id, count in counts.items():
        assignment = assignments[assignment_id]
        if count > assignment.periods_per_week:
            return "Có phân công đang vượt số tiết/tuần. Hãy đưa bớt tiết về kho trước khi lưu."
    for item in lessons:
        assignment = assignments[item["assignment_id"]]
        error = imported_draft_target_error(
            db, project, assignment, item["slot"], lessons, assignments,
            exclude_draft_id=item["draft_id"],
            accepted_unavailable=accepted_unavailable,
        )
        if error:
            return error
    for assignment_id in counts:
        error = imported_draft_pattern_error(project, assignments[assignment_id], lessons)
        if error:
            return error
    return None

def convert_schedule_file_to_draft(
    pid: int,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project(pid, user, db)
    filename, content = read_schedule_upload(file)
    from app.schedule_audit import ScheduleAuditParseError, analyze_schedule_file
    data = project_data(db, project)
    try:
        report = analyze_schedule_file(
            filename=filename,
            content=content,
            project=data["project"],
            classes=data["classes"],
            subjects=data["subjects"],
            teachers=data["teachers"],
            assignments=data["assignments"],
            include_editable=True,
        )
    except ScheduleAuditParseError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
    except Exception:
        logger.exception("schedule import conversion failed for project %s", pid)
        return JSONResponse(
            {"ok": False, "message": "Không thể chuyển file thành bản nháp chỉnh sửa."},
            status_code=500,
        )
    editable = report.pop("editable_lessons", [])
    if not editable:
        return JSONResponse(
            {"ok": False, "message": "Không có tiết nào đủ thông tin để chuyển sang chỉnh sửa kéo-thả."},
            status_code=400,
        )
    stem = os.path.splitext(os.path.basename(filename))[0].strip() or "TKB import"
    suggested_name = f"{project.name} - {stem}"[:200]
    return {
        "ok": True,
        "filename": filename,
        "suggested_name": suggested_name,
        "lessons": editable,
        "audit": report,
    }

def edit_imported_schedule_draft(
    pid: int,
    payload: ImportedScheduleEditIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project(pid, user, db)
    lessons, assignments = normalize_import_draft_lessons(db, project, payload.lessons)
    action = payload.action.strip().lower()
    if action not in {"move", "add", "remove"}:
        raise HTTPException(400, "Thao tác chỉnh sửa bản nháp không hợp lệ.")

    if action == "remove":
        if payload.draft_id is None:
            raise HTTPException(400, "Thiếu mã tiết cần gỡ.")
        before = len(lessons)
        lessons = [item for item in lessons if item["draft_id"] != payload.draft_id]
        if len(lessons) == before:
            raise HTTPException(404, "Không tìm thấy tiết cần gỡ trong bản nháp.")
        return {"ok": True, "lessons": lessons, "message": "Đã đưa tiết về kho của bản nháp."}

    if payload.slot is None:
        raise HTTPException(400, "Thiếu ô đích của thời khóa biểu.")

    if action == "move":
        if payload.draft_id is None:
            raise HTTPException(400, "Thiếu mã tiết cần di chuyển.")
        lesson = next((item for item in lessons if item["draft_id"] == payload.draft_id), None)
        if lesson is None:
            raise HTTPException(404, "Không tìm thấy tiết cần di chuyển trong bản nháp.")
        assignment = assignments[lesson["assignment_id"]]
        error = imported_draft_target_error(
            db, project, assignment, payload.slot, lessons, assignments,
            exclude_draft_id=lesson["draft_id"],
        )
        if error:
            return JSONResponse({"ok": False, "message": error}, status_code=409)
        updated = [dict(item) for item in lessons]
        for item in updated:
            if item["draft_id"] == lesson["draft_id"]:
                item["slot"] = payload.slot
                break
        error = imported_draft_pattern_error(project, assignment, updated)
        if error:
            return JSONResponse({"ok": False, "message": error}, status_code=409)
        return {"ok": True, "lessons": updated, "message": "Đã di chuyển tiết trong bản nháp."}

    if payload.assignment_id is None:
        raise HTTPException(400, "Thiếu phân công cần thêm vào lịch.")
    assignment = assignments.get(payload.assignment_id)
    if assignment is None:
        raise HTTPException(404, "Phân công không còn tồn tại.")
    scheduled = sum(1 for item in lessons if item["assignment_id"] == assignment.id)
    if scheduled >= assignment.periods_per_week:
        return JSONResponse({"ok": False, "message": "Phân công này đã đủ số tiết/tuần."}, status_code=409)
    error = imported_draft_target_error(db, project, assignment, payload.slot, lessons, assignments)
    if error:
        return JSONResponse({"ok": False, "message": error}, status_code=409)
    next_draft_id = max((item["draft_id"] for item in lessons), default=0) + 1
    updated = [*lessons, {"draft_id": next_draft_id, "assignment_id": assignment.id, "slot": payload.slot}]
    error = imported_draft_pattern_error(project, assignment, updated)
    if error:
        return JSONResponse({"ok": False, "message": error}, status_code=409)
    return {"ok": True, "lessons": updated, "message": "Đã thêm tiết vào bản nháp."}

def create_project_from_imported_schedule(
    db: Session,
    source: Project,
    owner_id: int,
    name: str,
    lessons: list[dict[str, int]],
) -> Project:
    project = Project(
        owner_id=owner_id,
        name=name,
        school_name=source.school_name,
        days=source.days,
        sessions=source.sessions,
        periods_per_session=source.periods_per_session,
        blocked_slots_json=source.blocked_slots_json,
    )
    db.add(project)
    db.flush()
    maps = {"dep": {}, "sub": {}, "tea": {}, "grade": {}, "cls": {}, "ass": {}}
    for row in db.scalars(select(Department).where(Department.project_id == source.id)).all():
        new = Department(project_id=project.id, name=row.name)
        db.add(new); db.flush(); maps["dep"][row.id] = new.id
    for row in db.scalars(select(Subject).where(Subject.project_id == source.id)).all():
        new = Subject(project_id=project.id, name=row.name, short_name=row.short_name, max_consecutive=row.max_consecutive)
        db.add(new); db.flush(); maps["sub"][row.id] = new.id
    for row in db.scalars(select(Teacher).where(Teacher.project_id == source.id)).all():
        new = Teacher(
            project_id=project.id,
            department_id=maps["dep"].get(row.department_id),
            name=row.name,
            short_name=row.short_name,
            max_periods_day=row.max_periods_day,
            unavailable_json=row.unavailable_json,
        )
        db.add(new); db.flush(); maps["tea"][row.id] = new.id
    for row in db.scalars(select(TeacherSubject).where(TeacherSubject.project_id == source.id)).all():
        if row.teacher_id in maps["tea"] and row.subject_id in maps["sub"]:
            db.add(TeacherSubject(
                project_id=project.id,
                teacher_id=maps["tea"][row.teacher_id],
                subject_id=maps["sub"][row.subject_id],
            ))
    for row in db.scalars(select(TeacherPreference).where(
        TeacherPreference.project_id == source.id,
        TeacherPreference.status == "accepted",
    )).all():
        if row.teacher_id in maps["tea"]:
            db.add(TeacherPreference(
                project_id=project.id,
                teacher_id=maps["tea"][row.teacher_id],
                preferred_json=row.preferred_json,
                unavailable_json=row.unavailable_json,
                note=row.note,
                status="accepted",
                created_at=row.created_at,
                reviewed_at=row.reviewed_at,
            ))
    for row in db.scalars(select(Grade).where(Grade.project_id == source.id)).all():
        new = Grade(project_id=project.id, name=row.name)
        db.add(new); db.flush(); maps["grade"][row.id] = new.id
    for row in db.scalars(select(GradeSubjectRequirement).where(GradeSubjectRequirement.project_id == source.id)).all():
        if row.grade_id in maps["grade"] and row.subject_id in maps["sub"]:
            db.add(GradeSubjectRequirement(
                project_id=project.id,
                grade_id=maps["grade"][row.grade_id],
                subject_id=maps["sub"][row.subject_id],
                periods_per_week=row.periods_per_week,
                block_mode=row.block_mode,
            ))
    for row in db.scalars(select(SchoolClass).where(SchoolClass.project_id == source.id)).all():
        new = SchoolClass(
            project_id=project.id,
            grade_id=maps["grade"].get(row.grade_id),
            name=row.name,
            unavailable_json=row.unavailable_json,
        )
        db.add(new); db.flush(); maps["cls"][row.id] = new.id
    for row in db.scalars(select(Assignment).where(Assignment.project_id == source.id)).all():
        new = Assignment(
            project_id=project.id,
            class_id=maps["cls"][row.class_id],
            subject_id=maps["sub"][row.subject_id],
            teacher_id=maps["tea"][row.teacher_id],
            periods_per_week=row.periods_per_week,
            block_mode=row.block_mode,
            consecutive_pattern="",
        )
        db.add(new); db.flush(); maps["ass"][row.id] = new.id
    for item in lessons:
        mapped_assignment_id = maps["ass"].get(item["assignment_id"])
        if mapped_assignment_id is None:
            raise HTTPException(400, "Không thể ánh xạ một phân công khi lưu TKB import.")
        db.add(Lesson(
            project_id=project.id,
            assignment_id=mapped_assignment_id,
            slot=item["slot"],
            locked=False,
        ))
    return project

def save_imported_schedule_as_project(
    pid: int,
    payload: ImportedScheduleSaveIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    source = get_project_for_update(pid, user, db)
    clean_name = payload.name.strip()
    if not clean_name:
        raise HTTPException(400, "Tên thời khóa biểu không được để trống.")
    lessons, assignments = normalize_import_draft_lessons(db, source, payload.lessons)
    error = imported_draft_validation_error(db, source, lessons, assignments)
    if error:
        return JSONResponse(
            {"ok": False, "message": f"Chưa thể lưu: {error}"},
            status_code=409,
        )
    project = create_project_from_imported_schedule(db, source, user.id, clean_name, lessons)
    db.commit()
    return {
        "ok": True,
        "project_id": project.id,
        "dashboard_url": "/projects",
        "message": "Đã lưu TKB import thành một bộ thời khóa biểu mới trên Dashboard.",
    }


@app.get("/projects/{pid}/chatbot", response_class=HTMLResponse)
def chatbot_page(pid:int, request:Request, user:User=Depends(current_user), db:Session=Depends(db_session)):
    p=get_project(pid,user,db)
    return templates.TemplateResponse("chatbot.html", {
        "request":request,
        "user":user,
        "p":p,
        "chatbot_enabled":bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "chatbot_primary_model":os.getenv("GEMINI_MODEL", "gemini-3.7-flash").strip() or "gemini-3.7-flash",
    })

@app.post("/api/projects/{pid}/chatbot")
def chatbot_reply(
    pid:int,
    message:str=Form(...),
    history_json:str=Form("[]"),
    document_context_json:str=Form("[]"),
    preferred_model:str=Form(""),
    files:list[UploadFile]|None=File(None),
    user:User=Depends(current_user),
    db:Session=Depends(db_session),
):
    from app.chatbot import (
        MAX_TOTAL_UPLOAD_BYTES,
        MAX_UPLOAD_BYTES,
        MAX_UPLOAD_FILES,
        ChatbotError,
        ask_gemini,
        parse_uploaded_table,
    )

    p=get_project(pid,user,db)
    clean_message=message.strip()
    if not clean_message:
        raise HTTPException(400,"Hãy nhập nội dung cần tư vấn")
    if len(clean_message)>4000:
        raise HTTPException(400,"Nội dung không được vượt quá 4.000 ký tự")
    try:
        raw_history=json.loads(history_json)
    except (json.JSONDecodeError,TypeError):
        raise HTTPException(400,"Lịch sử trò chuyện không hợp lệ")
    if not isinstance(raw_history,list):
        raise HTTPException(400,"Lịch sử trò chuyện không hợp lệ")
    history=[]
    for item in raw_history[-8:]:
        if not isinstance(item,dict) or item.get("role") not in {"user","assistant"}:
            continue
        content=str(item.get("content","")).strip()
        if content:
            history.append({"role":item["role"],"content":content[:8000]})

    if len(document_context_json)>MAX_CHATBOT_DOCUMENT_CONTEXT_CHARS:
        raise HTTPException(400,"Ngữ cảnh tệp của cuộc trò chuyện quá lớn. Hãy xóa cuộc trò chuyện và đính kèm lại tệp cần dùng.")
    try:
        retained_documents=json.loads(document_context_json)
    except (json.JSONDecodeError,TypeError):
        raise HTTPException(400,"Ngữ cảnh tệp của cuộc trò chuyện không hợp lệ")
    if not isinstance(retained_documents,list) or any(not isinstance(item,dict) for item in retained_documents):
        raise HTTPException(400,"Ngữ cảnh tệp của cuộc trò chuyện không hợp lệ")

    upload_items=[item for item in (files or []) if item.filename]
    if len(upload_items)>MAX_UPLOAD_FILES:
        raise HTTPException(400,f"Chỉ được đính kèm tối đa {MAX_UPLOAD_FILES} tệp")
    uploaded_tables=[]
    total_upload_bytes=0
    for file in upload_items:
        content=file.file.read(MAX_UPLOAD_BYTES+1)
        total_upload_bytes+=len(content)
        if total_upload_bytes>MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(400,"Tổng dung lượng tệp vượt quá giới hạn 12 MB")
        try:
            uploaded_tables.append(parse_uploaded_table(file.filename,content))
        except ChatbotError as exc:
            raise HTTPException(400,str(exc))

    document_map={}
    for document in [*retained_documents,*uploaded_tables]:
        filename=str(document.get("filename","")).strip()[:200]
        document_type=str(document.get("type","")).strip()[:20]
        if not filename or not document_type:
            continue
        document_map[(filename,document_type)]=document
    document_context=list(document_map.values())
    if len(json.dumps(document_context,ensure_ascii=False,separators=(",",":")))>MAX_CHATBOT_DOCUMENT_CONTEXT_CHARS:
        raise HTTPException(400,"Ngữ cảnh tệp của cuộc trò chuyện quá lớn. Hãy xóa cuộc trò chuyện và chỉ đính kèm các tệp cần thiết.")

    def persist_chatbot_failure(error_code: str, error_message: str, provider_status: int | None = None) -> None:
        try:
            db.add(ChatbotErrorLog(
                project_id=p.id,
                project_name=p.name,
                user_id=user.id,
                user_name=user.name,
                user_email=user.email,
                error_code=error_code[:64],
                provider_status=provider_status,
                error_message=error_message[:8000],
            ))
            db.commit()
            cutoff_id = db.scalar(
                select(ChatbotErrorLog.id)
                .order_by(ChatbotErrorLog.id.desc())
                .offset(MAX_CHATBOT_ERROR_LOGS - 1)
                .limit(1)
            )
            if cutoff_id is not None:
                db.execute(delete(ChatbotErrorLog).where(ChatbotErrorLog.id < cutoff_id))
                db.commit()
        except Exception:
            db.rollback()
            logger.exception("Could not persist chatbot error log for project %s", pid)

    try:
        answer, model_used, fallback_failures = ask_gemini(
            clean_message,
            history,
            project_data(db,p),
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
        raise HTTPException(503,"Không thể kết nối tới chatbot. Vui lòng thử lại sau.")
    except Exception as exc:
        logger.exception("Unexpected chatbot failure for project %s", pid)
        persist_chatbot_failure(
            "internal_error",
            f"{type(exc).__name__}: {exc}",
        )
        raise HTTPException(503,"Không thể kết nối tới chatbot. Vui lòng thử lại sau.")
    return {
        "answer":answer,
        "files_analyzed":len(uploaded_tables),
        "document_context":document_context,
        "model_used":model_used,
        "fallback_used":model_used != (os.getenv("GEMINI_MODEL", "gemini-3.7-flash").strip() or "gemini-3.7-flash"),
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
            raise HTTPException(400, "Danh sách môn của giáo viên không hợp lệ") from exc
        if subject_id > 0 and subject_id not in result:
            result.append(subject_id)
    if not result:
        return []
    found = set(db.scalars(select(Subject.id).where(
        Subject.project_id == project_id,
        Subject.id.in_(result),
    )).all())
    if found != set(result):
        raise HTTPException(400, "Có môn học không thuộc bộ thời khóa biểu")
    return result

def replace_teacher_subjects(db: Session, project_id: int, teacher_id: int, subject_ids: list[int]) -> None:
    rows = db.scalars(select(TeacherSubject).where(
        TeacherSubject.project_id == project_id,
        TeacherSubject.teacher_id == teacher_id,
    )).all()
    existing = {row.subject_id: row for row in rows}
    wanted = set(subject_ids)
    for subject_id, row in existing.items():
        if subject_id not in wanted:
            db.delete(row)
    for subject_id in subject_ids:
        if subject_id not in existing:
            db.add(TeacherSubject(project_id=project_id, teacher_id=teacher_id, subject_id=subject_id))

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
            mode = normalized_block_mode(item.get("block_mode", "free"), periods, subject, project)
        except ValueError as exc:
            raise HTTPException(400, f"{subject.name}: {exc}") from exc
        configs[subject_id] = (periods, mode)
    return [(subject_id, periods, mode) for subject_id, (periods, mode) in configs.items()]

def replace_grade_requirements(
    db: Session, project: Project, grade_id: int, values
) -> None:
    configs = normalized_grade_requirements(db, project, values)
    rows = db.scalars(select(GradeSubjectRequirement).where(
        GradeSubjectRequirement.project_id == project.id,
        GradeSubjectRequirement.grade_id == grade_id,
    )).all()
    existing = {row.subject_id: row for row in rows}
    wanted = {subject_id for subject_id, _, _ in configs}
    for subject_id, row in existing.items():
        if subject_id not in wanted:
            db.delete(row)
    for subject_id, periods, mode in configs:
        row = existing.get(subject_id)
        if row is None:
            db.add(GradeSubjectRequirement(
                project_id=project.id, grade_id=grade_id, subject_id=subject_id,
                periods_per_week=periods, block_mode=mode,
            ))
        else:
            row.periods_per_week = periods
            row.block_mode = mode

def teacher_week_capacity(
    project: Project,
    teacher: Teacher,
    max_periods_day: int | None = None,
    unavailable_slots: set[int] | None = None,
    extra_unavailable: set[int] | None = None,
    project_blocked_slots: set[int] | None = None,
) -> int:
    daily_limit = max_periods_day if max_periods_day is not None else teacher.max_periods_day
    periods_per_day = project.sessions * project.periods_per_session
    project_blocked = project_blocked_slots if project_blocked_slots is not None else set(valid_slots(
        project, parse_slots(project.blocked_slots_json), strict=False,
    ))
    teacher_blocked = (
        parse_slots(teacher.unavailable_json)
        if unavailable_slots is None else set(unavailable_slots)
    ) | set(extra_unavailable or set())
    teacher_blocked = set(valid_slots(project, teacher_blocked, strict=False))
    capacity = 0
    for day in range(project.days):
        start = day * periods_per_day
        available = sum(
            1 for slot in range(start, start + periods_per_day)
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
    project_blocked = project_blocked_slots if project_blocked_slots is not None else set(valid_slots(
        project, parse_slots(project.blocked_slots_json), strict=False,
    ))
    class_blocked = parse_slots(school_class.unavailable_json) if unavailable_slots is None else unavailable_slots
    class_blocked = set(valid_slots(project, class_blocked, strict=False))
    return maximum - len(project_blocked | class_blocked)

def teacher_assigned_periods(db: Session, project_id: int, teacher_id: int) -> int:
    value = db.scalar(select(func.coalesce(func.sum(Assignment.periods_per_week), 0)).where(
        Assignment.project_id == project_id,
        Assignment.teacher_id == teacher_id,
    ))
    return int(value or 0)

def class_assigned_periods(db: Session, project_id: int, class_id: int) -> int:
    value = db.scalar(select(func.coalesce(func.sum(Assignment.periods_per_week), 0)).where(
        Assignment.project_id == project_id,
        Assignment.class_id == class_id,
    ))
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
    _preferred, accepted_unavailable = accepted_teacher_preferences(db, project.id)
    capacity = teacher_week_capacity(
        project,
        teacher,
        max_periods_day=max_periods_day,
        unavailable_slots=unavailable_slots,
        extra_unavailable=accepted_unavailable.get(teacher.id, set()),
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

def duplicate_assignment_issues(db: Session, assignments: list[Assignment]) -> list[dict]:
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
            teacher_names.append(teacher.name if teacher else f"Giáo viên #{row.teacher_id}")
        issues.append({
            "class_id": class_id,
            "class_name": school_class.name if school_class else f"Lớp #{class_id}",
            "subject_id": subject_id,
            "subject_name": subject.name if subject else f"Môn #{subject_id}",
            "assignment_ids": sorted(row.id for row in rows),
            "teacher_names": teacher_names,
        })
    return sorted(issues, key=lambda item: (item["class_name"], item["subject_name"]))

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
        assigned_by_teacher[assignment.teacher_id] += int(assignment.periods_per_week or 0)

    _preferred, accepted_unavailable = accepted_teacher_preferences(db, project.id)
    project_blocked = set(valid_slots(
        project, parse_slots(project.blocked_slots_json), strict=False,
    ))
    issues = []
    for teacher_id, assigned in assigned_by_teacher.items():
        teacher = db.get(Teacher, teacher_id)
        if not teacher:
            continue
        capacity = teacher_week_capacity(
            project,
            teacher,
            extra_unavailable=accepted_unavailable.get(teacher.id, set()),
            project_blocked_slots=project_blocked,
        )
        if assigned > capacity:
            issues.append({
                "teacher_id": teacher.id,
                "teacher_name": teacher.name,
                "assigned": assigned,
                "capacity": capacity,
                "excess": assigned - capacity,
            })
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
            issues.append({
                "class_id": school_class.id,
                "class_name": school_class.name,
                "assigned": assigned,
                "capacity": capacity,
                "excess": assigned - capacity,
            })
    return sorted(issues, key=lambda item: (-item["excess"], item["class_name"]))

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
def add_entity(pid:int, payload:EntityIn, user:User=Depends(current_user), db:Session=Depends(db_session)):
    project=get_project_for_update(pid,user,db); d=payload.data
    teacher_subject_ids: list[int] | None = None
    if payload.type=="department":
        obj=Department(project_id=pid,name=required_text(d,"name","Tên tổ chuyên môn",120))
    elif payload.type=="subject":
        name=required_text(d,"name","Tên môn học",120)
        ensure_unique_project_name(db, Subject, pid, name, "Môn học")
        max_consecutive=bounded_int(d.get("max_consecutive"),2,1,4,"Số tiết liên tiếp tối đa")
        short_name=(str(d.get("short_name") or "").strip() or name[:5])[:20]
        obj=Subject(project_id=pid,name=name,short_name=short_name,max_consecutive=max_consecutive)
    elif payload.type=="teacher":
        name=required_text(d,"name","Tên giáo viên",120)
        department_id=d.get("department_id") or None
        if department_id:
            try: department_id=int(department_id)
            except (TypeError,ValueError) as exc: raise HTTPException(400,"Tổ chuyên môn không hợp lệ") from exc
            department=db.get(Department,department_id)
            if not department or department.project_id!=pid: raise HTTPException(400,"Tổ chuyên môn không hợp lệ")
        max_periods_day=bounded_int(d.get("max_periods_day"),5,1,10,"Số tiết tối đa mỗi ngày")
        short_name=(str(d.get("short_name") or "").strip() or name)[:30]
        teacher_subject_ids=validated_subject_ids(db,pid,d.get("subject_ids",[]))
        obj=Teacher(project_id=pid,name=name,short_name=short_name,department_id=department_id,max_periods_day=max_periods_day,unavailable_json=json.dumps(valid_slots(project,d.get("unavailable",[]))))
    elif payload.type=="grade":
        obj=Grade(project_id=pid,name=required_text(d,"name","Tên khối lớp",80))
    elif payload.type=="class":
        name=required_text(d,"name","Tên lớp học",80)
        ensure_unique_project_name(db, SchoolClass, pid, name, "Lớp học")
        grade_id=d.get("grade_id") or None
        if grade_id:
            try: grade_id=int(grade_id)
            except (TypeError,ValueError) as exc: raise HTTPException(400,"Khối lớp không hợp lệ") from exc
            grade=db.get(Grade,grade_id)
            if not grade or grade.project_id!=pid: raise HTTPException(400,"Khối lớp không hợp lệ")
        obj=SchoolClass(project_id=pid,name=name,grade_id=grade_id,unavailable_json=json.dumps(valid_slots(project,d.get("unavailable",[]))))
    elif payload.type=="assignment":
        class_id=required_id(d,"class_id","Lớp học")
        subject_id=required_id(d,"subject_id","Môn học")
        teacher_id=required_id(d,"teacher_id","Giáo viên")
        school_class=db.get(SchoolClass,class_id); subject=db.get(Subject,subject_id); teacher=db.get(Teacher,teacher_id)
        if not school_class or not subject or not teacher or any(x.project_id!=pid for x in (school_class,subject,teacher)):
            raise HTTPException(400,"Lớp, môn hoặc giáo viên không thuộc bộ thời khóa biểu")
        allowed=db.scalar(select(TeacherSubject.id).where(
            TeacherSubject.project_id==pid,
            TeacherSubject.teacher_id==teacher.id,
            TeacherSubject.subject_id==subject.id,
        ))
        if allowed is None:
            raise HTTPException(409,f"{teacher.name} chưa được cấu hình dạy môn {subject.name}")
        duplicate=db.scalar(select(Assignment).where(
            Assignment.project_id==pid,
            Assignment.class_id==school_class.id,
            Assignment.subject_id==subject.id,
        ))
        if duplicate is not None:
            if duplicate.teacher_id==teacher.id:
                raise HTTPException(409,"Phân công lớp – môn này đã tồn tại")
            other=db.get(Teacher,duplicate.teacher_id)
            raise HTTPException(409,f"{school_class.name} – {subject.name} đã được phân công cho {other.name if other else 'giáo viên khác'}")
        periods=bounded_int(d.get("periods_per_week"),1,1,40,"Số tiết mỗi tuần")
        try: mode=normalized_block_mode(d.get("block_mode","free"),periods,subject,project)
        except ValueError as exc: raise HTTPException(400,str(exc)) from exc
        ensure_teacher_load_fits(db,project,teacher,teacher_assigned_periods(db,pid,teacher.id)+periods)
        ensure_class_load_fits(
            project,school_class,class_assigned_periods(db,pid,school_class.id)+periods,
        )
        obj=Assignment(project_id=pid,class_id=school_class.id,subject_id=subject.id,teacher_id=teacher.id,periods_per_week=periods,block_mode=mode,consecutive_pattern="")
    else: raise HTTPException(400,"Loại dữ liệu không hợp lệ")
    db.add(obj)
    db.flush()
    if payload.type=="teacher" and teacher_subject_ids is not None:
        replace_teacher_subjects(db,pid,obj.id,teacher_subject_ids)
    if payload.type=="grade":
        replace_grade_requirements(db,project,obj.id,d.get("subject_requirements",[]))
    db.commit(); return {"ok":True,"id":obj.id}

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

    class_ids = list(dict.fromkeys(int(value) for value in payload.class_ids if int(value) > 0))
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

    subjects = db.scalars(select(Subject).where(
        Subject.project_id == pid,
        Subject.id.in_(subject_ids),
    )).all()
    classes = db.scalars(select(SchoolClass).where(
        SchoolClass.project_id == pid,
        SchoolClass.id.in_(class_ids),
    )).all()
    subject_map = {item.id: item for item in subjects}
    class_map = {item.id: item for item in classes}
    if set(subject_map) != set(subject_ids):
        raise HTTPException(400, "Có môn học không thuộc bộ thời khóa biểu")
    if set(class_map) != set(class_ids):
        raise HTTPException(400, "Có lớp học không thuộc bộ thời khóa biểu")

    allowed_subject_ids = set(db.scalars(select(TeacherSubject.subject_id).where(
        TeacherSubject.project_id == pid,
        TeacherSubject.teacher_id == teacher.id,
        TeacherSubject.subject_id.in_(subject_ids),
    )).all())
    not_allowed = [subject_map[sid].name for sid in subject_ids if sid not in allowed_subject_ids]
    if not_allowed:
        raise HTTPException(
            409,
            f"{teacher.name} chưa được cấu hình dạy: {', '.join(not_allowed)}",
        )

    normalized: dict[int, tuple[int, str]] = {}
    for subject_id, config in configs.items():
        subject = subject_map[subject_id]
        periods = bounded_int(config.periods_per_week, 1, 1, 40, f"Số tiết/tuần của {subject.name}")
        try:
            mode = normalized_block_mode(config.block_mode, periods, subject, project)
        except ValueError as exc:
            raise HTTPException(400, f"{subject.name}: {exc}") from exc
        normalized[subject_id] = (periods, mode)

    existing_rows = db.scalars(select(Assignment).where(
        Assignment.project_id == pid,
        Assignment.subject_id.in_(subject_ids),
        Assignment.class_id.in_(class_ids),
    )).all()
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
        suffix = f"; và {len(conflicts)-5} cặp khác" if len(conflicts) > 5 else ""
        raise HTTPException(
            409,
            f"Không thể tạo vì môn của lớp đã được phân công cho giáo viên khác: {preview}{suffix}.",
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
            class_assigned_periods(db,pid,class_id)+class_added_periods,
        )

    created = 0
    skipped = 0
    for subject_id in subject_ids:
        periods, mode = normalized[subject_id]
        for class_id in class_ids:
            if (subject_id, class_id) in existing_pairs:
                skipped += 1
                continue
            db.add(Assignment(
                project_id=pid,
                class_id=class_id,
                subject_id=subject_id,
                teacher_id=teacher.id,
                periods_per_week=periods,
                block_mode=mode,
                consecutive_pattern="",
            ))
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
    model = {"subject": Subject, "teacher": Teacher, "grade": Grade, "class": SchoolClass}[typ]
    obj = db.get(model, eid)
    if not obj or obj.project_id != pid:
        raise HTTPException(404, "Không tìm thấy dữ liệu cần sửa")
    d = payload.data
    name_limit = {"subject": 120, "teacher": 120, "grade": 80, "class": 80}[typ]
    name = bounded_text(d.get("name", ""), "Tên", name_limit)
    if typ == "subject":
        ensure_unique_project_name(db, Subject, pid, name, "Môn học", exclude_id=obj.id)
        short_name = bounded_text(d.get("short_name", ""), "Tên rút gọn", 20)
        new_max_consecutive = bounded_int(
            d.get("max_consecutive"), 1, 1, 4, "Số tiết liên tiếp tối đa"
        )
        assignments = db.scalars(select(Assignment).where(
            Assignment.project_id == pid,
            Assignment.subject_id == obj.id,
        )).all()
        incompatible_assignments = [
            assignment.id for assignment in assignments
            if getattr(assignment,"block_mode","free") in {"preferred_double","required_double"}
            and assignment.periods_per_week >= 2
            and new_max_consecutive < 2
        ]

        assignment_by_id = {assignment.id: assignment for assignment in assignments}
        periods_by_class_session = defaultdict(list)
        periods_per_day = project.sessions * project.periods_per_session
        if assignment_by_id:
            lessons = db.scalars(select(Lesson).where(
                Lesson.project_id == pid,
                Lesson.assignment_id.in_(list(assignment_by_id)),
            )).all()
            for lesson in lessons:
                assignment = assignment_by_id.get(lesson.assignment_id)
                if not assignment:
                    continue
                day = lesson.slot // periods_per_day
                inside_day = lesson.slot % periods_per_day
                session = inside_day // project.periods_per_session
                period = inside_day % project.periods_per_session
                periods_by_class_session[(assignment.class_id, day, session)].append(period)

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
        department_id = d.get("department_id") or None
        if department_id is not None:
            try:
                department_id = int(department_id)
            except (TypeError, ValueError) as exc:
                raise HTTPException(400, "Tổ chuyên môn không hợp lệ") from exc
            department = db.get(Department, department_id)
            if not department or department.project_id != pid:
                raise HTTPException(400, "Tổ chuyên môn không hợp lệ")
        new_max_periods_day = bounded_int(
            d.get("max_periods_day"), 5, 1, 10, "Số tiết tối đa mỗi ngày"
        )
        assignment_ids = set(db.scalars(select(Assignment.id).where(
            Assignment.project_id == pid,
            Assignment.teacher_id == obj.id,
        )).all())
        if assignment_ids:
            ppd = project.sessions * project.periods_per_session
            daily_counts = Counter(
                slot // ppd
                for slot in db.scalars(select(Lesson.slot).where(
                    Lesson.project_id == pid,
                    Lesson.assignment_id.in_(assignment_ids),
                )).all()
            )
            highest_current = max(daily_counts.values(), default=0)
            if highest_current > new_max_periods_day:
                raise HTTPException(
                    409,
                    f"Không thể giảm còn {new_max_periods_day} tiết/ngày vì lịch hiện tại có ngày giáo viên đang dạy {highest_current} tiết. Hãy điều chỉnh lịch trước.",
                )
        assigned_total = teacher_assigned_periods(db, pid, obj.id)
        ensure_teacher_load_fits(db, project, obj, assigned_total, max_periods_day=new_max_periods_day)
        if "subject_ids" in d:
            teacher_subject_ids = validated_subject_ids(db, pid, d.get("subject_ids"))
            assigned_subject_ids = set(db.scalars(select(Assignment.subject_id).where(
                Assignment.project_id == pid,
                Assignment.teacher_id == obj.id,
            )).all())
            removed_in_use = assigned_subject_ids - set(teacher_subject_ids)
            if removed_in_use:
                names = db.scalars(select(Subject.name).where(Subject.id.in_(removed_in_use))).all()
                raise HTTPException(
                    409,
                    "Không thể bỏ môn đang có phân công: " + ", ".join(names) + ". Hãy xóa/chuyển phân công trước.",
                )
            replace_teacher_subjects(db, pid, obj.id, teacher_subject_ids)
        obj.name = name
        obj.short_name = short_name
        obj.department_id = department_id
        obj.max_periods_day = new_max_periods_day
    elif typ == "grade":
        obj.name = name
        replace_grade_requirements(db, project, obj.id, d.get("subject_requirements", []))
    else:
        ensure_unique_project_name(db, SchoolClass, pid, name, "Lớp học", exclude_id=obj.id)
        grade_id = d.get("grade_id") or None
        if grade_id is not None:
            try:
                grade_id = int(grade_id)
            except (TypeError, ValueError) as exc:
                raise HTTPException(400, "Khối lớp không hợp lệ") from exc
            grade = db.get(Grade, grade_id)
            if not grade or grade.project_id != pid:
                raise HTTPException(400, "Khối lớp không hợp lệ")
        obj.name = name
        obj.grade_id = grade_id
    db.commit()
    return {"ok": True}

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
    locked_slots=sorted(lesson.slot for lesson in lessons if lesson.locked)
    replacement_rows=[]
    if assignment_requires_double(assignment):
        expected=Counter(assignment_groups(assignment))
        used=Counter()
        for run in assignment_run_groups(project,locked_slots):
            size=run["size"]
            if expected[size]<=used[size]:
                return (
                    "Các tiết cố định hiện tại không tạo thành các cặp/tiết lẻ "
                    "hợp lệ theo chế độ bắt buộc tiết đôi mới. Hãy bỏ cố định "
                    "hoặc sắp xếp lại các tiết cố định trước."
                )
            used[size]+=1
            replacement_rows.append((run["start"],size))
    else:
        replacement_rows=[(slot,1) for slot in locked_slots]

    fixed_rows=db.scalars(select(FixedLesson).where(
        FixedLesson.project_id==project.id,
        FixedLesson.assignment_id==assignment.id,
    )).all()
    for row in fixed_rows:
        db.delete(row)
    for slot,size in replacement_rows:
        db.add(FixedLesson(
            project_id=project.id,
            assignment_id=assignment.id,
            slot=slot,
            group_size=size,
        ))
    return None


@app.put("/api/projects/{pid}/assignments/{assignment_id}")
def update_assignment(pid:int,assignment_id:int,payload:AssignmentUpdateIn,user:User=Depends(current_user),db:Session=Depends(db_session)):
    project=get_project_for_update(pid,user,db)
    assignment=db.get(Assignment,assignment_id)
    if not assignment or assignment.project_id!=pid: raise HTTPException(404)
    periods=bounded_int(payload.periods_per_week,1,1,40,"Số tiết mỗi tuần")
    lessons=db.scalars(select(Lesson).where(Lesson.assignment_id==assignment.id)).all()
    scheduled=len(lessons)
    if periods<scheduled:
        return JSONResponse({"ok":False,"message":f"Đang có {scheduled} tiết trên lịch. Hãy gỡ bớt tiết trước khi giảm số tiết/tuần."},409)
    subject=db.get(Subject,assignment.subject_id)
    if not subject or subject.project_id!=pid: raise HTTPException(409,"Môn học của phân công không còn tồn tại")
    try: mode=normalized_block_mode(payload.block_mode,periods,subject,project)
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc

    old_periods=assignment.periods_per_week
    old_mode=assignment.block_mode
    teacher=db.get(Teacher,assignment.teacher_id)
    if not teacher or teacher.project_id!=pid:
        raise HTTPException(409,"Giáo viên của phân công không còn tồn tại")
    projected_total=teacher_assigned_periods(db,pid,teacher.id)-old_periods+periods
    ensure_teacher_load_fits(db,project,teacher,projected_total)
    school_class=db.get(SchoolClass,assignment.class_id)
    if not school_class or school_class.project_id!=pid:
        raise HTTPException(409,"Lớp của phân công không còn tồn tại")
    projected_class_total=class_assigned_periods(db,pid,school_class.id)-old_periods+periods
    ensure_class_load_fits(project,school_class,projected_class_total)
    periods_changed=periods!=old_periods
    mode_changed=mode!=old_mode

    # Không xóa các Lesson đang có. Thay đổi được áp dụng trong transaction và
    # sẽ rollback nguyên vẹn nếu phần lịch hiện tại không tương thích.
    assignment.periods_per_week=periods
    assignment.block_mode=mode
    assignment.consecutive_pattern=""

    if mode_changed or (periods_changed and assignment_requires_double(assignment)):
        fixed_error=normalize_assignment_fixed_rows(db,project,assignment,lessons)
        if fixed_error:
            db.rollback()
            return JSONResponse({"ok":False,"message":fixed_error},409)

    # Chỉ các thay đổi ảnh hưởng cấu trúc cụm mới cần chứng minh rằng những tiết
    # đã xếp vẫn có ít nhất một cách hoàn thành. Tăng số tiết ở chế độ tự do/
    # ưu tiên chỉ tạo phần còn thiếu trong khay và giữ nguyên toàn bộ lịch cũ.
    if (mode_changed or (periods_changed and assignment_requires_double(assignment))) and not assignment_completion_feasible(
        db,project,assignment,[lesson.slot for lesson in lessons]
    ):
        db.rollback()
        return JSONResponse({
            "ok":False,
            "message":"Không thể áp dụng thay đổi vì các tiết hiện có không thể hoàn thành hợp lệ theo chế độ mới và các ràng buộc hiện tại. Lịch cũ được giữ nguyên.",
        },409)

    db.commit();return {"ok":True,"scheduled_preserved":scheduled}

@app.delete("/api/projects/{pid}/entity/{typ}/{eid}")
def delete_entity(pid:int,typ:str,eid:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    get_project_for_update(pid,user,db)
    model={"department":Department,"subject":Subject,"teacher":Teacher,"grade":Grade,"class":SchoolClass,"assignment":Assignment}.get(typ)
    if not model: raise HTTPException(400)
    obj=db.get(model,eid)
    if not obj or obj.project_id!=pid: raise HTTPException(404)
    dependency={
        "department":db.scalar(select(Teacher.id).where(Teacher.department_id==eid)),
        "subject":db.scalar(select(Assignment.id).where(Assignment.subject_id==eid))
            or db.scalar(select(GradeSubjectRequirement.id).where(GradeSubjectRequirement.subject_id==eid)),
        "teacher":db.scalar(select(Assignment.id).where(Assignment.teacher_id==eid)),
        "grade":db.scalar(select(SchoolClass.id).where(SchoolClass.grade_id==eid)),
        "class":db.scalar(select(Assignment.id).where(Assignment.class_id==eid)),
    }.get(typ)
    if dependency is not None:
        return JSONResponse({"ok":False,"message":"Không thể xóa vì dữ liệu đang được sử dụng."},409)
    if typ=="teacher" and account_for_teacher(eid, db) is not None:
        return JSONResponse({"ok":False,"message":"Hãy thu hồi tài khoản giáo viên trước khi xóa."},409)
    if typ=="assignment":
        for l in db.scalars(select(Lesson).where(Lesson.assignment_id==eid)).all(): db.delete(l)
        for fixed_lesson in db.scalars(select(FixedLesson).where(FixedLesson.assignment_id==eid)).all(): db.delete(fixed_lesson)
    if typ=="subject":
        for link in db.scalars(select(TeacherSubject).where(TeacherSubject.subject_id==eid)).all():
            db.delete(link)
        for requirement in db.scalars(select(GradeSubjectRequirement).where(GradeSubjectRequirement.subject_id==eid)).all():
            db.delete(requirement)
    if typ=="grade":
        for requirement in db.scalars(select(GradeSubjectRequirement).where(GradeSubjectRequirement.grade_id==eid)).all():
            db.delete(requirement)
    if typ=="teacher":
        for link in db.scalars(select(TeacherSubject).where(TeacherSubject.teacher_id==eid)).all():
            db.delete(link)
        for preference in db.scalars(select(TeacherPreference).where(TeacherPreference.teacher_id==eid)).all():
            db.delete(preference)
        for verification in db.scalars(select(RegistrationVerification).where(
            RegistrationVerification.teacher_id==eid
        )).all():
            db.delete(verification)
    db.delete(obj); db.commit(); return {"ok":True}

class ConstraintIn(BaseModel):
    entity_type: str
    entity_id: int
    slots: list[int]

@app.post("/api/projects/{pid}/constraints")
def constraints(pid:int,payload:ConstraintIn,user:User=Depends(current_user),db:Session=Depends(db_session)):
    p=get_project_for_update(pid,user,db)
    if payload.entity_type not in {"teacher","class"}: raise HTTPException(400,"Loại ràng buộc không hợp lệ")
    model=Teacher if payload.entity_type=="teacher" else SchoolClass
    obj=db.get(model,payload.entity_id)
    if not obj or obj.project_id!=pid: raise HTTPException(404)
    slots=set(valid_slots(p,payload.slots))
    assignments=db.scalars(select(Assignment).where(
        Assignment.project_id==pid,
        Assignment.teacher_id==obj.id if payload.entity_type=="teacher" else Assignment.class_id==obj.id,
    )).all()
    assignment_ids={assignment.id for assignment in assignments}
    lessons=db.scalars(select(Lesson).where(
        Lesson.project_id==pid,
        Lesson.assignment_id.in_(assignment_ids),
    )).all() if assignment_ids else []
    lessons_by_assignment=defaultdict(list)
    for lesson in lessons:
        lessons_by_assignment[lesson.assignment_id].append(lesson)

    fixed_rows=db.scalars(select(FixedLesson).where(
        FixedLesson.project_id==pid,
        FixedLesson.assignment_id.in_(assignment_ids),
    )).all() if assignment_ids else []
    assignment_by_id={assignment.id:assignment for assignment in assignments}
    for row in fixed_rows:
        assignment=assignment_by_id.get(row.assignment_id)
        if not assignment:
            continue
        size=fixed_row_size(p,assignment,row,lessons_by_assignment[row.assignment_id])
        if slots.intersection(range(row.slot,row.slot+size)):
            return JSONResponse({"ok":False,"message":"Ràng buộc mới xung đột với tiết cố định. Hãy bỏ cố định trước."},409)

    removed_ids=set()
    for assignment in assignments:
        assignment_lessons=lessons_by_assignment[assignment.id]
        if not assignment_requires_double(assignment):
            affected=[lesson for lesson in assignment_lessons if lesson.slot in slots]
            if any(lesson.locked for lesson in affected):
                return JSONResponse({"ok":False,"message":"Ràng buộc mới xung đột với tiết cố định. Hãy bỏ cố định trước."},409)
            removed_ids.update(lesson.id for lesson in affected)
            continue
        for run in assignment_run_groups(p,[lesson.slot for lesson in assignment_lessons]):
            if not slots.intersection(run["slots"]):
                continue
            run_slots=set(run["slots"])
            affected=[lesson for lesson in assignment_lessons if lesson.slot in run_slots]
            if any(lesson.locked for lesson in affected):
                return JSONResponse({"ok":False,"message":"Ràng buộc mới xung đột với tiết cố định. Hãy bỏ cố định trước."},409)
            removed_ids.update(lesson.id for lesson in affected)

    if payload.entity_type=="teacher":
        ensure_teacher_load_fits(
            db,p,obj,teacher_assigned_periods(db,pid,obj.id),unavailable_slots=slots,
        )
    else:
        ensure_class_load_fits(
            p,obj,class_assigned_periods(db,pid,obj.id),unavailable_slots=slots,
        )
    obj.unavailable_json=json.dumps(sorted(slots))
    for lesson in lessons:
        if lesson.id in removed_ids:
            db.delete(lesson)
    db.commit()
    return {"ok":True,"removed":len(removed_ids)}

class SessionLocksIn(BaseModel):
    sessions: list[int] = Field(default_factory=list)
    slots: list[int] = Field(default_factory=list)

@app.post("/api/projects/{pid}/session-locks")
def save_session_locks(pid:int,payload:SessionLocksIn,user:User=Depends(current_user),db:Session=Depends(db_session)):
    project=get_project_for_update(pid,user,db)
    maximum=project.days*project.sessions
    session_keys=sorted({int(value) for value in payload.sessions if 0<=int(value)<maximum})
    blocked=[]
    ppd=project.sessions*project.periods_per_session
    for key in session_keys:
        day=key//project.sessions
        session=key%project.sessions
        start=day*ppd+session*project.periods_per_session
        blocked.extend(range(start,start+project.periods_per_session))
    blocked=valid_slots(project,[*blocked,*payload.slots])
    all_lessons=db.scalars(select(Lesson).where(Lesson.project_id==pid)).all()
    lessons_by_assignment=defaultdict(list)
    for lesson in all_lessons:
        lessons_by_assignment[lesson.assignment_id].append(lesson)
    fixed_rows=db.scalars(select(FixedLesson).where(FixedLesson.project_id==pid)).all()
    blocked_set=set(blocked)
    removed_ids=set()

    # Khóa buổi phải tuân cùng quy tắc với ràng buộc giáo viên/lớp:
    # không âm thầm xóa các cụm đã được cố định.
    for row in fixed_rows:
        assignment=db.get(Assignment,row.assignment_id)
        if not assignment:
            continue
        lessons=lessons_by_assignment.get(row.assignment_id,[])
        size=fixed_row_size(project,assignment,row,lessons)
        row_slots=set(range(row.slot,row.slot+size))
        if blocked_set.intersection(row_slots):
            return JSONResponse({
                "ok":False,
                "message":"Buổi hoặc tiết mới khóa đang chứa tiết cố định. Hãy bỏ cố định trước.",
            },409)
    if any(lesson.locked and lesson.slot in blocked_set for lesson in all_lessons):
        return JSONResponse({
            "ok":False,
            "message":"Buổi hoặc tiết mới khóa đang chứa tiết cố định. Hãy bỏ cố định trước.",
        },409)

    teachers=db.scalars(select(Teacher).where(Teacher.project_id==pid)).all()
    for teacher in teachers:
        assigned=teacher_assigned_periods(db,pid,teacher.id)
        if assigned:
            ensure_teacher_load_fits(
                db,project,teacher,assigned,project_blocked_slots=blocked_set,
            )
    classes=db.scalars(select(SchoolClass).where(SchoolClass.project_id==pid)).all()
    for school_class in classes:
        assigned=class_assigned_periods(db,pid,school_class.id)
        if assigned:
            ensure_class_load_fits(
                project,school_class,assigned,project_blocked_slots=blocked_set,
            )

    project.blocked_slots_json=json.dumps(blocked)
    for assignment_id,lessons in lessons_by_assignment.items():
        if not any(lesson.slot in blocked_set for lesson in lessons):
            continue
        assignment=db.get(Assignment,assignment_id)
        if not assignment:
            for lesson in lessons:
                if lesson.slot in blocked_set:
                    removed_ids.add(lesson.id)
            continue
        if not assignment_requires_double(assignment):
            removed_ids.update(lesson.id for lesson in lessons if lesson.slot in blocked_set)
            continue
        for run in assignment_run_groups(project,[lesson.slot for lesson in lessons]):
            if blocked_set.intersection(run["slots"]):
                run_slots=set(run["slots"])
                removed_ids.update(lesson.id for lesson in lessons if lesson.slot in run_slots)
    for lesson in all_lessons:
        if lesson.id in removed_ids:
            db.delete(lesson)
    db.commit()
    return {"ok":True,"sessions":session_keys,"removed":len(removed_ids)}

class FixedIn(BaseModel):
    assignment_id:int
    slot:int

def fixed_row_size(project: Project, assignment: Assignment, row: FixedLesson, lessons: list[Lesson] | None = None) -> int:
    if not assignment_requires_double(assignment):
        return 1
    expected = assignment_groups(assignment)
    size = int(getattr(row, "group_size", 1) or 1)
    if lessons:
        for run in assignment_run_groups(project, [lesson.slot for lesson in lessons]):
            if run["start"] == row.slot and row.slot in run["slots"] and run["size"] in expected:
                return run["size"]
    if size in expected and not (size == 1 and 1 not in expected):
        return size
    return expected[0] if expected else 1


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
        db.add(Lesson(
            project_id=project.id,
            assignment_id=assignment_id,
            slot=slot,
            locked=bool(locked or slot in fixed_slots[assignment_id]),
        ))

@app.post("/api/projects/{pid}/fixed")
def fixed(pid:int,payload:FixedIn,user:User=Depends(current_user),db:Session=Depends(db_session)):
    p=get_project_for_update(pid,user,db)
    assignment=db.get(Assignment,payload.assignment_id)
    if not assignment or assignment.project_id!=pid: raise HTTPException(404)
    if payload.slot not in set(all_slots(p)):
        raise HTTPException(400,"Ô thời khóa biểu không hợp lệ")
    lessons=db.scalars(select(Lesson).where(Lesson.project_id==pid,Lesson.assignment_id==assignment.id)).all()
    if assignment_requires_double(assignment):
        run=next((item for item in assignment_run_groups(p,[lesson.slot for lesson in lessons]) if payload.slot in item["slots"]),None)
    else:
        selected=next((lesson for lesson in lessons if lesson.slot==payload.slot),None)
        run={"start":payload.slot,"size":1,"slots":[payload.slot]} if selected else None
    if not run:
        # Tương thích với client cũ: payload.slot từng được hiểu là ô đích.
        # Chỉ cho phép khi phân công chưa có cụm cố định để tránh làm mất các ghim khác.
        existing_fixed=db.scalars(select(FixedLesson).where(FixedLesson.project_id==pid,FixedLesson.assignment_id==assignment.id)).all()
        if existing_fixed:
            raise HTTPException(409,"Hãy chọn trực tiếp một tiết đang có trên lịch để cố định tiết hoặc cặp đó")
        groups=assignment_groups(assignment)
        size=groups[0] if groups else 1
        day,session,period=slot_meta(p,payload.slot)
        if period+size>p.periods_per_session:
            raise HTTPException(409,"Cặp tiết cố định vượt quá cuối buổi học")
        for lesson in lessons:
            if lesson.locked:
                raise HTTPException(409,"Phân công đang có tiết cố định; không thể dùng chế độ di chuyển cũ")
            db.delete(lesson)
        db.add(FixedLesson(project_id=pid,assignment_id=assignment.id,slot=payload.slot,group_size=size))
        db.flush()
        result=solve_missing(db,p,tries=180,target_assignment_ids={assignment.id})
        target=[row for row in result["lessons"] if row[0]==assignment.id]
        if len(target)<assignment.periods_per_week:
            db.rollback()
            return JSONResponse({"ok":False,"message":"Không thể cố định phân công tại vị trí này vì xung đột lớp, giáo viên hoặc ràng buộc."},409)
        add_generated_lessons(db,p,result["lessons"])
        db.commit()
        return {"ok":True,"message":f"Đã chuyển và cố định {size} tiết tại ô đã chọn."}
    if remaining_pattern_groups(p,assignment,[lesson.slot for lesson in lessons]) is None:
        raise HTTPException(409,"Lịch hiện tại chưa phù hợp với chế độ xếp tiết; hãy xếp lại trước khi cố định")
    expected=Counter(assignment_groups(assignment))
    if expected[run["size"]] <= 0:
        raise HTTPException(409,"Tiết hoặc cặp đang chọn không phù hợp với chế độ của phân công")
    fixed_rows=db.scalars(select(FixedLesson).where(FixedLesson.project_id==pid,FixedLesson.assignment_id==assignment.id)).all()
    used=Counter()
    for row in fixed_rows:
        size=fixed_row_size(p,assignment,row,lessons)
        if row.slot==run["start"]:
            row.group_size=run["size"]
            for lesson in lessons:
                if lesson.slot in run["slots"]: lesson.locked=True
            db.commit()
            return {"ok":True,"message":f"Đã cố định {run['size']} tiết đang chọn."}
        used[size]+=1
    if used[run["size"]] >= expected[run["size"]]:
        raise HTTPException(409,"Số tiết/cặp cố định đã vượt số lượng cho phép của phân công")
    for lesson in lessons:
        if lesson.slot in run["slots"]:
            error=lesson_slot_error(db,p,assignment,lesson.slot,lesson.id)
            if error: raise HTTPException(409,error)
            lesson.locked=True
    db.add(FixedLesson(project_id=pid,assignment_id=assignment.id,slot=run["start"],group_size=run["size"]))
    db.commit()
    return {"ok":True,"message":f"Đã cố định {run['size']} tiết đang chọn."}

@app.delete("/api/projects/{pid}/fixed/{assignment_id}/{slot}")
def remove_fixed_group(pid:int,assignment_id:int,slot:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    p=get_project_for_update(pid,user,db)
    assignment=db.get(Assignment,assignment_id)
    if not assignment or assignment.project_id!=pid: raise HTTPException(404)
    lessons=db.scalars(select(Lesson).where(Lesson.project_id==pid,Lesson.assignment_id==assignment_id)).all()
    rows=db.scalars(select(FixedLesson).where(FixedLesson.project_id==pid,FixedLesson.assignment_id==assignment_id)).all()
    targets=[]
    for row in rows:
        size=fixed_row_size(p,assignment,row,lessons)
        if row.slot<=slot<row.slot+size:
            targets.append((row,size))
    if not targets:
        raise HTTPException(404,"Không tìm thấy tiết hoặc cặp cố định")
    unlocked=set()
    for row,size in targets:
        unlocked.update(range(row.slot,row.slot+size));db.delete(row)
    remaining=[]
    for row in rows:
        if all(row.id!=target.id for target,_size in targets):
            size=fixed_row_size(p,assignment,row,lessons)
            remaining.extend(range(row.slot,row.slot+size))
    for lesson in lessons:
        if lesson.slot in unlocked and lesson.slot not in remaining:
            lesson.locked=False
    db.commit()
    return {"ok":True,"message":"Đã bỏ cố định tiết hoặc cặp đang chọn."}

@app.delete("/api/projects/{pid}/fixed/{assignment_id}")
def remove_fixed(pid:int,assignment_id:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    get_project_for_update(pid,user,db)
    assignment=db.get(Assignment,assignment_id)
    if not assignment or assignment.project_id!=pid: raise HTTPException(404)
    fixed_rows=db.scalars(select(FixedLesson).where(FixedLesson.project_id==pid,FixedLesson.assignment_id==assignment_id)).all()
    for row in fixed_rows: db.delete(row)
    lessons=db.scalars(select(Lesson).where(Lesson.project_id==pid,Lesson.assignment_id==assignment_id)).all()
    for lesson in lessons: lesson.locked=False
    db.commit()
    return {"ok":True,"message":"Đã bỏ toàn bộ cố định của phân công."}

class GenerateScheduleIn(BaseModel):
    allow_rebuild: bool = False

@app.post("/api/projects/{pid}/generate")
def generate(pid:int,payload:Optional[GenerateScheduleIn]=None,user:User=Depends(current_user),db:Session=Depends(db_session)):
    p=get_project_for_update(pid,user,db)
    assignments=db.scalars(select(Assignment).where(Assignment.project_id==pid)).all()
    duplicate_issues=duplicate_assignment_issues(db,assignments)
    if duplicate_issues:
        details="; ".join(
            f"{item['class_name']} – {item['subject_name']} "
            f"(phân công ID {', '.join(map(str,item['assignment_ids']))})"
            for item in duplicate_issues[:5]
        )
        suffix=f"; và {len(duplicate_issues)-5} cặp khác" if len(duplicate_issues)>5 else ""
        return JSONResponse({
            "ok":False,
            "reason":"duplicate_assignments",
            "duplicate_assignment_issues":duplicate_issues,
            "message":(
                "Không thể xếp lịch vì một lớp–môn đang có nhiều phân công: "
                f"{details}{suffix}. Hãy xóa hoặc chuyển dữ liệu để mỗi lớp–môn "
                "chỉ còn một giáo viên rồi xếp lại."
            ),
        },409)
    capacity_issues=schedule_teacher_capacity_issues(db,p,assignments)
    if capacity_issues:
        details="; ".join(
            f"{item['teacher_name']}: đã phân công {item['assigned']} tiết, "
            f"tối đa xếp được {item['capacity']} tiết (dư {item['excess']})"
            for item in capacity_issues[:5]
        )
        suffix=(
            f"; và {len(capacity_issues)-5} giáo viên khác"
            if len(capacity_issues)>5 else ""
        )
        return JSONResponse({
            "ok":False,
            "reason":"teacher_over_capacity",
            "capacity_issues":capacity_issues,
            "message":(
                "Không thể xếp đầy đủ vì tải dạy vượt số ô khả dụng: "
                f"{details}{suffix}. Hãy giảm/chuyển phân công, tăng giới hạn "
                "tiết/ngày hoặc bỏ bớt tiết tránh rồi xếp lại."
            ),
        },409)
    classes=db.scalars(select(SchoolClass).where(SchoolClass.project_id==pid)).all()
    class_capacity_issues=schedule_class_capacity_issues(p,classes,assignments)
    if class_capacity_issues:
        details="; ".join(
            f"{item['class_name']}: cần {item['assigned']} tiết, "
            f"chỉ còn {item['capacity']} ô (dư {item['excess']})"
            for item in class_capacity_issues[:5]
        )
        suffix=(
            f"; và {len(class_capacity_issues)-5} lớp khác"
            if len(class_capacity_issues)>5 else ""
        )
        return JSONResponse({
            "ok":False,
            "reason":"class_over_capacity",
            "class_capacity_issues":class_capacity_issues,
            "message":(
                "Không thể xếp đầy đủ vì tải học của lớp vượt số ô khả dụng: "
                f"{details}{suffix}. Hãy giảm phân công hoặc bỏ bớt khóa/tiết tránh của lớp."
            ),
        },409)
    existing=db.scalars(select(Lesson).where(Lesson.project_id==pid)).all()
    assignment_by_id={assignment.id:assignment for assignment in assignments}

    # Chuẩn hóa dữ liệu cố định cũ và hỗ trợ nhiều cụm cố định trên một phân công.
    lessons_by_assignment=defaultdict(list)
    for lesson in existing:
        lessons_by_assignment[lesson.assignment_id].append(lesson)
    fixed_rows=db.scalars(select(FixedLesson).where(FixedLesson.project_id==pid)).all()
    fixed_changed=False
    assignments_with_unsatisfied_fixed=set()
    fixed_specs_by_assignment=defaultdict(list)
    for fixed_row in fixed_rows:
        assignment=assignment_by_id.get(fixed_row.assignment_id)
        if not assignment:
            db.delete(fixed_row);fixed_changed=True;continue
        size=fixed_row_size(p,assignment,fixed_row,lessons_by_assignment[assignment.id])
        fixed_specs_by_assignment[assignment.id].append((fixed_row.slot,size))
        if fixed_row.group_size!=size:
            fixed_row.group_size=size;fixed_changed=True
        expected_slots=set(range(fixed_row.slot,fixed_row.slot+size))
        matching={lesson.slot:lesson for lesson in lessons_by_assignment[assignment.id] if lesson.slot in expected_slots}
        if expected_slots.issubset(matching):
            for slot in expected_slots:
                if not matching[slot].locked:
                    matching[slot].locked=True;fixed_changed=True
        else:
            assignments_with_unsatisfied_fixed.add(assignment.id)

    for assignment_id,fixed_specs in fixed_specs_by_assignment.items():
        assignment=assignment_by_id[assignment_id]
        fixed_error=fixed_group_validation_error(
            assignment_groups(assignment),
            fixed_specs,
            days=p.days,
            sessions=p.sessions,
            periods_per_session=p.periods_per_session,
        )
        if fixed_error:
            return JSONResponse({
                "ok":False,
                "message":f"Dữ liệu tiết cố định của phân công không hợp lệ: {fixed_error} Hãy bỏ các ghim dư/trùng rồi xếp lại.",
            },409)

    for assignment_id in assignments_with_unsatisfied_fixed:
        for lesson in lessons_by_assignment[assignment_id]:
            if not lesson.locked:
                db.delete(lesson);fixed_changed=True
    if fixed_changed:
        db.flush()
        existing=db.scalars(select(Lesson).where(Lesson.project_id==pid)).all()

    # Rà lại lịch cũ trước mỗi lần xếp. Ràng buộc hoặc nguyện vọng có thể đã
    # thay đổi sau khi lịch được tạo, vì vậy không được coi "đủ tiết" là hợp lệ.
    invalid_lessons=[]
    rebuild_assignment_ids=set()
    for lesson in existing:
        assignment=assignment_by_id.get(lesson.assignment_id)
        if not assignment:
            invalid_lessons.append(lesson)
            continue
        if lesson_slot_error(
            db,p,assignment,lesson.slot,lesson.id,target_locked=bool(lesson.locked),
        ):
            if lesson.locked:
                invalid_lessons.append(lesson)
            elif assignment_requires_double(assignment):
                rebuild_assignment_ids.add(assignment.id)
            else:
                invalid_lessons.append(lesson)

    existing_by_assignment=defaultdict(list)
    for lesson in existing:
        existing_by_assignment[lesson.assignment_id].append(lesson)
    for assignment in assignments:
        lessons_for_assignment=existing_by_assignment[assignment.id]
        if not lessons_for_assignment:
            continue
        slots_for_assignment=[lesson.slot for lesson in lessons_for_assignment]
        remaining_groups=remaining_pattern_groups(p,assignment,slots_for_assignment)
        if remaining_groups is None:
            rebuild_assignment_ids.add(assignment.id)

    if rebuild_assignment_ids:
        # Với required_double, lỗi ở một tiết di động chỉ yêu cầu dựng lại phần
        # di động của phân công. Các tiết khóa hợp lệ phải được giữ lại; chỉ khi
        # chính tập tiết khóa không thể thuộc bất kỳ mẫu hợp lệ nào mới báo lỗi
        # cố định.
        for assignment_id in rebuild_assignment_ids:
            assignment=assignment_by_id.get(assignment_id)
            assignment_lessons=[
                lesson for lesson in existing if lesson.assignment_id==assignment_id
            ]
            locked_assignment_lessons=[lesson for lesson in assignment_lessons if lesson.locked]
            if assignment and locked_assignment_lessons:
                locked_slots=[lesson.slot for lesson in locked_assignment_lessons]
                if remaining_pattern_groups(p,assignment,locked_slots) is None:
                    invalid_lessons.extend(locked_assignment_lessons)
            invalid_lessons.extend(
                lesson for lesson in assignment_lessons if not lesson.locked
            )
    invalid_lessons=list({lesson.id:lesson for lesson in invalid_lessons}.values())
    locked_invalid=[lesson for lesson in invalid_lessons if lesson.locked]
    if locked_invalid:
        return JSONResponse({
            "ok":False,
            "message":f"Có {len(locked_invalid)} tiết cố định xung đột với ràng buộc hoặc chế độ xếp tiết mới. Hãy bỏ cố định hoặc điều chỉnh ràng buộc trước khi xếp lại.",
        },409)
    for lesson in invalid_lessons:
        db.delete(lesson)
    if invalid_lessons:
        db.flush()
        existing=db.scalars(select(Lesson).where(Lesson.project_id==pid)).all()

    # Tính số tiết còn thiếu theo từng phân công, không lấy tổng toàn project.
    # Cách này vẫn đúng nếu dữ liệu cũ/import từng bị lệch giữa các phân công
    # (một phân công thừa tiết trong khi phân công khác lại thiếu).
    existing_counts=Counter(lesson.assignment_id for lesson in existing)
    missing=sum(
        max(0,assignment.periods_per_week-existing_counts[assignment.id])
        for assignment in assignments
    )

    # Từ lần xếp thứ hai trở đi, tuyệt đối giữ nguyên các tiết đang có.
    # Chỉ bổ sung những tiết còn thiếu trong khay; nếu lịch đã đủ thì không làm gì.
    if existing:
        if missing == 0:
            if invalid_lessons or fixed_changed:
                db.commit()
            return {
                "ok":True,"score":0,"unscheduled":0,
                "message":"Thời khóa biểu đã đủ tiết. Các vị trí hiện tại được giữ nguyên.",
            }
        result=solve_missing(db,p,tries=160)
        if result["unscheduled"]>0:
            # Các tiết đang có có thể tự chặn phần còn thiếu. Thử giữ nguyên
            # tiết cố định và tái tối ưu toàn bộ phần không cố định.
            rebuild=solve_rebuild(db,p,tries=260)
            if rebuild["unscheduled"]>0:
                if rebuild.get("proven_infeasible"):
                    message="Các ràng buộc và tiết cố định hiện tại không cho phép tạo một thời khóa biểu đầy đủ."
                else:
                    message=(
                        f"Chưa tìm được lịch đầy đủ sau các bước bổ sung và tái tối ưu; "
                        f"còn {rebuild['unscheduled']} tiết chưa xếp. Dữ liệu lịch hiện tại chưa bị thay đổi."
                    )
                return JSONResponse({
                    "ok":False,"score":rebuild["score"],"unscheduled":rebuild["unscheduled"],
                    "message":message,
                },409)
            current_lessons=db.scalars(select(Lesson).where(Lesson.project_id==pid)).all()
            moved_count=sum(1 for lesson in current_lessons if not lesson.locked)
            if not payload or not payload.allow_rebuild:
                return JSONResponse({
                    "ok":False,
                    "requires_confirmation":True,
                    "moved_count":moved_count,
                    "message":(
                        "Không thể chỉ bổ sung phần còn thiếu mà giữ nguyên toàn bộ lịch hiện tại. "
                        f"Để hoàn thành thời khóa biểu, hệ thống cần xếp lại {moved_count} tiết không cố định; "
                        "các tiết cố định vẫn được giữ nguyên."
                    ),
                },409)
            for lesson in current_lessons:
                if not lesson.locked:
                    db.delete(lesson)
            db.flush()
            add_generated_lessons(db,p,rebuild["lessons"])
            db.commit()
            return {
                "ok":True,"score":rebuild["score"],"unscheduled":0,
                "message":f"Đã giữ nguyên các tiết cố định và xếp lại {moved_count} tiết không cố định để hoàn thành thời khóa biểu.",
            }
        add_generated_lessons(db,p,result["lessons"])
        db.commit()
        return {
            "ok":True,"score":result["score"],"unscheduled":0,
            "message":f"Đã xếp bổ sung {len(result['lessons'])} tiết từ khay và giữ nguyên các vị trí còn hợp lệ.",
        }

    # Chỉ khi lịch hoàn toàn trống mới chạy bộ xếp toàn bộ.
    result=solve(db,p,tries=120)
    if result["unscheduled"]>0:
        if result.get("proven_infeasible"):
            message="Các ràng buộc hiện tại không cho phép tạo một thời khóa biểu đầy đủ."
        else:
            message=f"Chưa tìm được lịch đầy đủ sau số lần thử hiện tại; còn {result['unscheduled']} tiết chưa xếp. Lịch hiện tại được giữ nguyên."
        return JSONResponse({
            "ok":False,"score":result["score"],"unscheduled":result["unscheduled"],
            "message":message,
        },409)
    for l in existing: db.delete(l)
    add_generated_lessons(db,p,result["lessons"])
    db.commit()
    return {"ok":True,"score":result["score"],"unscheduled":0,"message":f"Đã xếp đầy đủ {len(result['lessons'])} tiết."}

def lesson_slot_error(
    db:Session,project:Project,assignment:Assignment,slot:int,
    exclude_lesson_id:Optional[int]=None,*,target_locked:bool=False,
):
    if slot not in all_slots(project): return "Ô thời khóa biểu không hợp lệ."
    if slot in parse_slots(project.blocked_slots_json): return "Buổi này đã bị khóa và không được xếp tiết."
    teacher=db.get(Teacher,assignment.teacher_id);school_class=db.get(SchoolClass,assignment.class_id);subject=db.get(Subject,assignment.subject_id)
    if not teacher or not school_class or not subject: return "Phân công không còn đầy đủ lớp, môn hoặc giáo viên."
    if slot in parse_slots(teacher.unavailable_json): return "Giáo viên không thể dạy ở tiết này theo ràng buộc chính thức."
    _, accepted_unavailable = accepted_teacher_preferences(db, project.id)
    if slot in accepted_unavailable.get(teacher.id, set()):
        return "Tiết này nằm trong nguyện vọng cần tránh đã được duyệt của giáo viên."
    if slot in parse_slots(school_class.unavailable_json): return "Lớp không học ở tiết này."
    existing_lessons=db.scalars(select(Lesson).where(Lesson.project_id==project.id)).all()
    existing_lessons=[lesson for lesson in existing_lessons if lesson.id!=exclude_lesson_id]
    existing_lessons=schedule_validation_peers(
        existing_lessons,target_locked=target_locked,
    )
    for lesson in existing_lessons:
        if lesson.slot!=slot: continue
        other=db.get(Assignment,lesson.assignment_id)
        if other and (other.class_id==assignment.class_id or other.teacher_id==assignment.teacher_id):
            return "Ô đích bị trùng lớp hoặc giáo viên."
    ppd=project.sessions*project.periods_per_session;target_day=slot//ppd
    target_position=slot%ppd;target_session=target_position//project.periods_per_session
    teacher_periods=0;subject_periods=[]
    for lesson in existing_lessons:
        other=db.get(Assignment,lesson.assignment_id)
        if not other or lesson.slot//ppd!=target_day: continue
        if other.teacher_id==assignment.teacher_id: teacher_periods+=1
        position=lesson.slot%ppd
        if position//project.periods_per_session==target_session and other.class_id==assignment.class_id and other.subject_id==assignment.subject_id:
            subject_periods.append(position%project.periods_per_session)
    if teacher_periods>=teacher.max_periods_day: return "Giáo viên đã đạt số tiết tối đa trong ngày."
    run=sorted(subject_periods+[target_position%project.periods_per_session]);longest=current=1
    for left,right in zip(run,run[1:]):
        current=current+1 if right==left+1 else 1;longest=max(longest,current)
    if longest>subject.max_consecutive: return "Vượt số tiết liên tiếp tối đa của môn học."
    return None

class MoveIn(BaseModel):
    lesson_id:int
    slot:int

@app.post("/api/projects/{pid}/move")
def move(pid:int,payload:MoveIn,user:User=Depends(current_user),db:Session=Depends(db_session)):
    project=get_project_for_update(pid,user,db);lesson=db.get(Lesson,payload.lesson_id)
    if not lesson or lesson.project_id!=pid: raise HTTPException(404)
    if lesson.locked: return JSONResponse({"ok":False,"message":"Tiết cố định không thể di chuyển."},409)
    assignment=db.get(Assignment,lesson.assignment_id)
    if not assignment or assignment.project_id!=pid:
        return JSONResponse({"ok":False,"message":"Phân công của tiết học không còn tồn tại."},409)
    error=lesson_slot_error(db,project,assignment,payload.slot,lesson.id)
    if error: return JSONResponse({"ok":False,"message":error},409)
    assignment_lessons=db.scalars(select(Lesson).where(Lesson.assignment_id==assignment.id)).all()
    proposed_slots=[payload.slot if item.id==lesson.id else item.slot for item in assignment_lessons]
    if not assignment_completion_feasible(db,project,assignment,proposed_slots):
        return JSONResponse({"ok":False,"message":f"Vị trí này không thể hoàn thành hợp lệ theo chế độ {assignment_pattern_label(assignment)} và các ràng buộc hiện tại."},409)
    lesson.slot=payload.slot;db.commit();return {"ok":True}

class ManualLessonIn(BaseModel):
    assignment_id:int
    slot:int

@app.post("/api/projects/{pid}/lessons")
def add_manual_lesson(pid:int,payload:ManualLessonIn,user:User=Depends(current_user),db:Session=Depends(db_session)):
    project=get_project_for_update(pid,user,db);assignment=db.get(Assignment,payload.assignment_id)
    if not assignment or assignment.project_id!=pid: raise HTTPException(404)
    scheduled=db.scalar(select(func.count(Lesson.id)).where(Lesson.assignment_id==assignment.id)) or 0
    if scheduled>=assignment.periods_per_week:
        return JSONResponse({"ok":False,"message":"Phân công này đã đủ số tiết/tuần."},409)
    error=lesson_slot_error(db,project,assignment,payload.slot)
    if error: return JSONResponse({"ok":False,"message":error},409)
    current_slots=db.scalars(select(Lesson.slot).where(Lesson.assignment_id==assignment.id)).all()
    proposed_slots=[*current_slots,payload.slot]
    if not assignment_completion_feasible(db,project,assignment,proposed_slots):
        return JSONResponse({"ok":False,"message":f"Vị trí này không thể hoàn thành hợp lệ theo chế độ {assignment_pattern_label(assignment)} và các ràng buộc hiện tại."},409)
    lesson=Lesson(project_id=pid,assignment_id=assignment.id,slot=payload.slot,locked=False)
    db.add(lesson);db.commit();return {"ok":True,"id":lesson.id}

@app.delete("/api/projects/{pid}/lessons/{lesson_id}")
def remove_manual_lesson(pid:int,lesson_id:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    project=get_project_for_update(pid,user,db);lesson=db.get(Lesson,lesson_id)
    if not lesson or lesson.project_id!=pid: raise HTTPException(404)
    if lesson.locked: return JSONResponse({"ok":False,"message":"Tiết cố định không thể gỡ."},409)
    assignment=db.get(Assignment,lesson.assignment_id)
    if not assignment or assignment.project_id!=pid:
        return JSONResponse({"ok":False,"message":"Phân công của tiết học không còn tồn tại."},409)

    lessons=db.scalars(select(Lesson).where(Lesson.assignment_id==assignment.id)).all()
    remove_ids={lesson.id}
    if assignment_requires_double(assignment):
        slots_to_remove=required_double_removal_slots(
            [item.slot for item in lessons],
            lesson.slot,
            project.sessions,
            project.periods_per_session,
        )
        group=[item for item in lessons if item.slot in slots_to_remove]
        if any(item.locked for item in group):
            return JSONResponse({"ok":False,"message":"Cụm tiết đôi có tiết cố định nên không thể gỡ."},409)
        remove_ids={item.id for item in group}

    for item in lessons:
        if item.id in remove_ids:
            db.delete(item)
    db.commit()
    removed=len(remove_ids)
    message="Đã trả tiết về kho." if removed==1 else f"Đã trả cả cụm {removed} tiết về kho."
    return {"ok":True,"removed":removed,"message":message}

@app.delete("/api/projects/{pid}/assignments/{assignment_id}/lessons")
def return_assignment_to_tray(pid:int,assignment_id:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    get_project_for_update(pid,user,db);assignment=db.get(Assignment,assignment_id)
    if not assignment or assignment.project_id!=pid: raise HTTPException(404)
    lessons=db.scalars(select(Lesson).where(Lesson.project_id==pid,Lesson.assignment_id==assignment_id)).all()
    removable=[lesson for lesson in lessons if not lesson.locked];locked=len(lessons)-len(removable)
    for lesson in removable: db.delete(lesson)
    db.commit()
    message=f"Đã đưa {len(removable)} tiết về khay."
    if locked: message+=f" Còn {locked} tiết cố định được giữ lại."
    return {"ok":True,"removed":len(removable),"locked":locked,"message":message}

@app.delete("/api/projects/{pid}/lessons")
def return_all_to_tray(pid:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    get_project_for_update(pid,user,db);lessons=db.scalars(select(Lesson).where(Lesson.project_id==pid)).all()
    removable=[lesson for lesson in lessons if not lesson.locked];locked=len(lessons)-len(removable)
    for lesson in removable: db.delete(lesson)
    db.commit()
    message=f"Đã đưa {len(removable)} tiết về khay."
    if locked: message+=f" Còn {locked} tiết cố định được giữ lại."
    return {"ok":True,"removed":len(removable),"locked":locked,"message":message}

@app.get("/api/projects/{pid}/data")
def api_data(pid:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    p=get_project(pid,user,db);return project_data(db,p)

class TeacherAccountIn(BaseModel):
    teacher_id: int
    email: str
    password: str = ""

@app.get("/api/projects/{pid}/teacher-accounts")
def list_teacher_accounts(pid:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    get_project(pid,user,db)
    teachers=db.scalars(select(Teacher).where(Teacher.project_id==pid).order_by(Teacher.name)).all()
    items=[]
    for teacher in teachers:
        account=account_for_teacher(teacher.id,db)
        items.append({
            "teacher_id":teacher.id,
            "teacher_name":teacher.name,
            "account_id":account.id if account else None,
            "email":account.email if account else None,
        })
    return {"items":items}

@app.post("/api/projects/{pid}/teacher-accounts")
def save_teacher_account(pid:int,payload:TeacherAccountIn,user:User=Depends(current_user),db:Session=Depends(db_session)):
    # Khóa project để hai yêu cầu cấp cùng một tài khoản trong cùng project
    # không thể đồng thời vượt qua bước kiểm tra liên kết.
    get_project_for_update(pid,user,db)
    teacher=db.get(Teacher,payload.teacher_id)
    if not teacher or teacher.project_id!=pid: raise HTTPException(404,"Giáo viên không thuộc bộ thời khóa biểu")
    email=bounded_text(payload.email.lower(),"Email",255)
    if "@" not in email: raise HTTPException(400,"Email không hợp lệ")
    account=account_for_teacher(teacher.id,db)
    email_owner=db.scalar(select(User).where(User.email==email).with_for_update())
    if email_owner and (not account or email_owner.id!=account.id):
        if email_owner.role!="teacher" or not admin_can_manage_account(user,email_owner,db):
            raise HTTPException(409,"Email đã được sử dụng")
        account=email_owner
    if account:
        linked_teacher_ids=account_teacher_ids(account,db)-{teacher.id}
        linked_in_project=db.scalar(select(Teacher.id).where(
            Teacher.id.in_(linked_teacher_ids),
            Teacher.project_id==pid,
        )) if linked_teacher_ids else None
        if linked_in_project is not None:
            raise HTTPException(
                409,
                "Tài khoản này đã được liên kết với một giáo viên khác trong cùng bộ thời khóa biểu",
            )
        account.email=email; account.name=teacher.name
        if payload.password:
            if len(payload.password)<MIN_PASSWORD_LENGTH: raise HTTPException(400,f"Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự")
            account.password_hash=pwd.hash(payload.password)
            account.session_version+=1
    else:
        if len(payload.password)<MIN_PASSWORD_LENGTH: raise HTTPException(400,f"Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự")
        account=User(email=email,name=teacher.name,password_hash=pwd.hash(payload.password),role="teacher",teacher_id=teacher.id)
        db.add(account);db.flush()
    ensure_teacher_link(account,teacher,db)
    db.commit()
    return {"ok":True,"account_id":account.id}

@app.delete("/api/projects/{pid}/teacher-accounts/{teacher_id}")
def revoke_teacher_account(pid:int,teacher_id:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    get_project(pid,user,db)
    teacher=db.get(Teacher,teacher_id)
    if not teacher or teacher.project_id!=pid: raise HTTPException(404)
    account=account_for_teacher(teacher.id,db)
    if not account or account.role!="teacher": raise HTTPException(404)
    link=db.scalar(select(TeacherAccountLink).where(
        TeacherAccountLink.user_id==account.id,TeacherAccountLink.teacher_id==teacher.id
    ))
    if link:
        db.delete(link)
    remaining_ids=account_teacher_ids(account,db)-{teacher.id}
    if account.teacher_id==teacher.id:
        account.teacher_id=next(iter(remaining_ids),None)
    if not remaining_ids:
        revoke_last_teacher_profile(account)
    else:
        account.session_version+=1
    db.commit();return {"ok":True,"account_preserved":True}

def teacher_profiles_for_user(user:User,db:Session):
    if user.role!="teacher": raise HTTPException(403,"Tài khoản giáo viên không hợp lệ")
    teacher_ids=account_teacher_ids(user,db)
    if not teacher_ids: raise HTTPException(403,"Tài khoản giáo viên chưa được liên kết với hồ sơ nào")
    teachers=db.scalars(select(Teacher).where(Teacher.id.in_(teacher_ids))).all()
    profiles=[]
    for teacher in teachers:
        project=db.get(Project,teacher.project_id)
        if project:
            profiles.append((teacher,project))
    if not profiles: raise HTTPException(403,"Hồ sơ giáo viên không còn tồn tại")
    return sorted(profiles,key=lambda pair:pair[1].id,reverse=True)

def teacher_for_user(user:User,db:Session,project_id:Optional[int]=None):
    profiles=teacher_profiles_for_user(user,db)
    if project_id is not None:
        matches=[pair for pair in profiles if pair[1].id==project_id]
        if not matches: raise HTTPException(403,"Tài khoản không được cấp quyền cho bộ thời khóa biểu này")
        if len(matches)>1:
            raise HTTPException(
                409,
                "Tài khoản đang liên kết với nhiều giáo viên trong cùng bộ thời khóa biểu; quản trị viên cần thu hồi liên kết bị trùng",
            )
        return matches[0]
    latest_project_id=profiles[0][1].id
    latest_matches=[pair for pair in profiles if pair[1].id==latest_project_id]
    if len(latest_matches)>1:
        raise HTTPException(
            409,
            "Tài khoản đang liên kết với nhiều giáo viên trong cùng bộ thời khóa biểu; quản trị viên cần thu hồi liên kết bị trùng",
        )
    return profiles[0]

def teacher_project_data(db:Session,project:Project,teacher:Teacher):
    assignments=db.scalars(select(Assignment).where(
        Assignment.project_id==project.id,Assignment.teacher_id==teacher.id
    )).all()
    assignment_ids={item.id for item in assignments}
    class_ids={item.class_id for item in assignments}
    subject_ids={item.subject_id for item in assignments}
    classes={item.id:item for item in db.scalars(select(SchoolClass).where(
        SchoolClass.project_id==project.id,SchoolClass.id.in_(class_ids)
    )).all()} if class_ids else {}
    subjects={item.id:item for item in db.scalars(select(Subject).where(
        Subject.project_id==project.id,Subject.id.in_(subject_ids)
    )).all()} if subject_ids else {}
    grade_ids={item.grade_id for item in classes.values() if item.grade_id is not None}
    grades=db.scalars(select(Grade).where(
        Grade.project_id==project.id,Grade.id.in_(grade_ids)
    )).all() if grade_ids else []
    departments=[]
    if teacher.department_id is not None:
        department=db.scalar(select(Department).where(
            Department.project_id==project.id,Department.id==teacher.department_id
        ))
        if department:
            departments=[department]
    lessons=db.scalars(select(Lesson).where(
        Lesson.project_id==project.id,Lesson.assignment_id.in_(assignment_ids)
    )).all() if assignment_ids else []
    return {
        "project":{
            "id":project.id,"name":project.name,"school_name":project.school_name,
            "days":project.days,"sessions":project.sessions,"periods":project.periods_per_session,
            "blocked_slots":valid_slots(project,parse_slots(project.blocked_slots_json),strict=False),
        },
        "departments":[{"id":item.id,"name":item.name} for item in departments],
        "subjects":[{
            "id":item.id,"name":item.name,"short_name":item.short_name,
            "max_consecutive":item.max_consecutive,
        } for item in subjects.values()],
        "teachers":[{
            "id":teacher.id,"name":teacher.name,"short_name":teacher.short_name,
            "department_id":teacher.department_id,"max_periods_day":teacher.max_periods_day,
            "unavailable":list(parse_slots(teacher.unavailable_json)),
        }],
        "grades":[{"id":item.id,"name":item.name} for item in grades],
        "classes":[{
            "id":item.id,"name":item.name,"grade_id":item.grade_id,
            "unavailable":list(parse_slots(item.unavailable_json)),
        } for item in classes.values()],
        "assignments":[{
            "id":item.id,"class_id":item.class_id,"subject_id":item.subject_id,
            "teacher_id":item.teacher_id,"periods_per_week":item.periods_per_week,
            "block_mode":item.block_mode,
            "class_name":classes[item.class_id].name if item.class_id in classes else "?",
            "subject_name":subjects[item.subject_id].name if item.subject_id in subjects else "?",
            "subject_short":subjects[item.subject_id].short_name if item.subject_id in subjects else "?",
            "teacher_name":teacher.name,"teacher_short":teacher.short_name,
        } for item in assignments],
        "lessons":[{
            "id":item.id,"assignment_id":item.assignment_id,"slot":item.slot,"locked":item.locked,
        } for item in lessons],
        "coverage":{
            "unassigned_teachers":[],"unassigned_subjects":[],"unassigned_classes":[],
        },
    }

@app.get("/teacher",response_class=HTMLResponse)
def teacher_portal(request:Request,project_id:Optional[int]=None,user:User=Depends(current_user),db:Session=Depends(db_session)):
    teacher,project=teacher_for_user(user,db,project_id)
    profiles=teacher_profiles_for_user(user,db)
    preferences=[x for x in preference_payload(db,project) if x["teacher_id"]==teacher.id]
    return templates.TemplateResponse("teacher_portal.html",{
        "request":request,"user":user,"teacher":teacher,"p":project,
        "data":teacher_project_data(db,project,teacher),"preferences":preferences,"days":DAYS,
        "teacher_projects":[{"teacher":item_teacher,"project":item_project} for item_teacher,item_project in profiles],
    })

@app.get("/api/teacher/data")
def api_teacher_data(project_id:Optional[int]=None,user:User=Depends(current_user),db:Session=Depends(db_session)):
    teacher,project=teacher_for_user(user,db,project_id)
    return teacher_project_data(db,project,teacher)

@app.get("/teacher/account",response_class=HTMLResponse)
def teacher_account_page(request:Request,project_id:Optional[int]=None,user:User=Depends(current_user),db:Session=Depends(db_session)):
    teacher,project=teacher_for_user(user,db,project_id)
    return templates.TemplateResponse("teacher_account.html",{
        "request":request,"user":user,"teacher":teacher,"p":project,"error":None,"success":None,
    })

@app.post("/teacher/account",response_class=HTMLResponse)
def update_teacher_account(
    request:Request,
    email:str=Form(...),
    current_password:str=Form(...),
    new_password:str=Form(""),
    confirm_password:str=Form(""),
    project_id:Optional[int]=None,
    user:User=Depends(current_user),
    db:Session=Depends(db_session),
):
    teacher,project=teacher_for_user(user,db,project_id)
    context={"request":request,"user":user,"teacher":teacher,"p":project,"error":None,"success":None}
    if not pwd.verify(current_password,user.password_hash):
        context["error"]="Mật khẩu hiện tại không đúng."
        return templates.TemplateResponse("teacher_account.html",context,status_code=400)
    normalized_email=email.lower().strip()
    if not normalized_email or "@" not in normalized_email:
        context["error"]="Email không hợp lệ."
        return templates.TemplateResponse("teacher_account.html",context,status_code=400)
    if len(normalized_email)>255:
        context["error"]="Email không được vượt quá 255 ký tự."
        return templates.TemplateResponse("teacher_account.html",context,status_code=400)
    email_owner=db.scalar(select(User).where(User.email==normalized_email,User.id!=user.id))
    if email_owner:
        context["error"]="Email đã được sử dụng bởi tài khoản khác."
        return templates.TemplateResponse("teacher_account.html",context,status_code=409)
    password_changed=bool(new_password)
    if password_changed:
        if len(new_password)<MIN_PASSWORD_LENGTH:
            context["error"]=f"Mật khẩu mới phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự."
            return templates.TemplateResponse("teacher_account.html",context,status_code=400)
        if new_password!=confirm_password:
            context["error"]="Xác nhận mật khẩu mới không khớp."
            return templates.TemplateResponse("teacher_account.html",context,status_code=400)
        user.password_hash=pwd.hash(new_password)
        user.session_version+=1
    user.email=normalized_email
    db.commit()
    context["user"]=user
    context["success"]="Thông tin tài khoản đã được cập nhật."
    response=templates.TemplateResponse("teacher_account.html",context)
    if password_changed:
        set_session_cookie(response,user)
    return response

@app.get("/share/{token}",response_class=HTMLResponse)
def shared(token:str,request:Request,db:Session=Depends(db_session)):
    p=db.scalar(select(Project).where(Project.share_token==token))
    if not p: raise HTTPException(404)
    return templates.TemplateResponse("share.html",{"request":request,"p":p,"data":public_project_data(db,p),"days":DAYS})

@app.get("/preferences/{token}",response_class=HTMLResponse)
def teacher_preferences_page(token:str,request:Request,user:User=Depends(current_user),db:Session=Depends(db_session)):
    p=db.scalar(select(Project).where(Project.share_token==token))
    if not p: raise HTTPException(404)
    teacher,teacher_project=teacher_for_user(user,db,p.id)
    latest_preference=db.scalar(
        select(TeacherPreference).where(
            TeacherPreference.project_id==p.id,
            TeacherPreference.teacher_id==teacher.id,
        ).order_by(TeacherPreference.id.desc())
    )
    latest_payload=None
    if latest_preference:
        latest_payload={
            "id":latest_preference.id,
            "preferred_slots":valid_slots(p,parse_slots(latest_preference.preferred_json),strict=False),
            "unavailable_slots":valid_slots(p,parse_slots(latest_preference.unavailable_json),strict=False),
            "note":latest_preference.note,
            "status":latest_preference.status,
            "created_at":latest_preference.created_at,
        }
    return templates.TemplateResponse(
        "teacher_preferences.html",
        {"request":request,"p":p,"teacher":teacher,"days":DAYS,"latest_preference":latest_payload},
    )

class TeacherPreferenceIn(BaseModel):
    teacher_id: int
    preferred_slots: list[int] = Field(default_factory=list)
    unavailable_slots: list[int] = Field(default_factory=list)
    note: str = ""

@app.post("/api/preferences/{token}")
def submit_teacher_preference(token:str,payload:TeacherPreferenceIn,user:User=Depends(current_user),db:Session=Depends(db_session)):
    # Dùng cùng khóa project với luồng duyệt để nội dung nguyện vọng không thể
    # bị thay đổi giữa lúc quản trị viên đang áp dụng nó vào lịch.
    p=db.scalar(select(Project).where(Project.share_token==token).with_for_update())
    if not p: raise HTTPException(404)
    teacher,teacher_project=teacher_for_user(user,db,p.id)
    if payload.teacher_id!=teacher.id: raise HTTPException(403,"Không thể gửi nguyện vọng thay giáo viên khác")
    preferred=set(valid_slots(p,payload.preferred_slots))
    unavailable=set(valid_slots(p,payload.unavailable_slots))
    preferred-=unavailable
    note=payload.note.strip()[:1000]
    pending=db.scalar(
        select(TeacherPreference).where(
            TeacherPreference.project_id==p.id,
            TeacherPreference.teacher_id==teacher.id,
            TeacherPreference.status=="pending",
        ).order_by(TeacherPreference.id.desc()).with_for_update()
    )
    if pending:
        # Trạng thái được đọc lại sau khi đã lấy khóa giao dịch.
        if pending.status!="pending":
            raise HTTPException(409,"Nguyện vọng này đang được xử lý, vui lòng tải lại trang")
        pending.preferred_json=json.dumps(sorted(preferred))
        pending.unavailable_json=json.dumps(sorted(unavailable))
        pending.note=note
        pending.created_at=datetime.now().isoformat(timespec="seconds")
        preference=pending
    else:
        preference=TeacherPreference(
            project_id=p.id,
            teacher_id=teacher.id,
            preferred_json=json.dumps(sorted(preferred)),
            unavailable_json=json.dumps(sorted(unavailable)),
            note=note,
        )
        db.add(preference)
    db.commit()
    return {"ok":True,"message":"Nguyện vọng đã được gửi đến người xếp thời khóa biểu."}

def preference_payload(db:Session,p:Project):
    rows=db.scalars(
        select(TeacherPreference).where(TeacherPreference.project_id==p.id).order_by(TeacherPreference.id.desc())
    ).all()
    teachers={x.id:x for x in db.scalars(select(Teacher).where(Teacher.project_id==p.id))}
    def label(slot:int):
        day,session,period=slot_meta(p,slot)
        session_text=f"{'Sáng' if session==0 else 'Chiều'} · " if p.sessions>1 else ""
        return f"{DAYS[day]} · {session_text}Tiết {period+1}"
    items=[]
    for row in rows:
        preferred_slots=valid_slots(p,parse_slots(row.preferred_json),strict=False)
        unavailable_slots=valid_slots(p,parse_slots(row.unavailable_json),strict=False)
        items.append({
            "id":row.id,
            "teacher_id":row.teacher_id,
            "teacher_name":teachers[row.teacher_id].name if row.teacher_id in teachers else "?",
            "preferred_slots":preferred_slots,
            "unavailable_slots":unavailable_slots,
            "preferred_labels":[label(slot) for slot in preferred_slots],
            "unavailable_labels":[label(slot) for slot in unavailable_slots],
            "note":row.note,
            "status":row.status,
            "created_at":row.created_at,
            "reviewed_at":row.reviewed_at,
        })
    return items

@app.get("/api/projects/{pid}/preferences")
def list_teacher_preferences(pid:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    p=get_project(pid,user,db)
    return {"items":preference_payload(db,p),"submission_url":f"/preferences/{p.share_token}"}

class PreferenceReviewIn(BaseModel):
    action: str

@app.post("/api/projects/{pid}/preferences/{preference_id}/review")
def review_teacher_preference(pid:int,preference_id:int,payload:PreferenceReviewIn,user:User=Depends(current_user),db:Session=Depends(db_session)):
    p=get_project_for_update(pid,user,db)
    preference=db.get(TeacherPreference,preference_id)
    if not preference or preference.project_id!=pid: raise HTTPException(404)
    if payload.action not in {"accept","reject"}: raise HTTPException(400,"Thao tác không hợp lệ")
    if preference.status!="pending":
        raise HTTPException(409,"Nguyện vọng này đã được xử lý")
    if payload.action=="reject":
        preference.status="rejected"
        preference.reviewed_at=datetime.now().isoformat(timespec="seconds")
        db.commit()
        return {"ok":True,"message":"Đã từ chối nguyện vọng."}

    preferred=set(valid_slots(p,parse_slots(preference.preferred_json),strict=False))
    unavailable=set(valid_slots(p,parse_slots(preference.unavailable_json),strict=False))
    teacher_assignments=db.scalars(select(Assignment).where(
        Assignment.project_id==pid,
        Assignment.teacher_id==preference.teacher_id,
    )).all()
    assignment_ids={assignment.id for assignment in teacher_assignments}
    teacher_lessons=db.scalars(select(Lesson).where(
        Lesson.project_id==pid,
        Lesson.assignment_id.in_(assignment_ids),
    )).all() if assignment_ids else []

    original_slots=defaultdict(list)
    for lesson in teacher_lessons:
        original_slots[lesson.assignment_id].append(lesson.slot)

    locked_conflicts=[
        lesson for lesson in teacher_lessons
        if lesson.locked and lesson.slot in unavailable
    ]
    if locked_conflicts:
        return JSONResponse({
            "ok":False,
            "message":f"Không thể duyệt vì có {len(locked_conflicts)} tiết cố định nằm trong các tiết cần tránh. Hãy bỏ cố định hoặc sửa nguyện vọng trước.",
        },409)

    def preference_cost(slots):
        values=list(slots)
        preferred_count=sum(1 for slot in values if slot in preferred)
        return -preferred_count

    old_cost=preference_cost(lesson.slot for lesson in teacher_lessons)
    old_assignment_valid=all(
        len(original_slots[assignment.id])==assignment.periods_per_week
        and assignment_pattern_matches(p,assignment,original_slots[assignment.id])
        for assignment in teacher_assignments
    )
    old_hard_valid=all(lesson.slot not in unavailable for lesson in teacher_lessons)

    previous=db.scalars(select(TeacherPreference).where(
        TeacherPreference.project_id==pid,
        TeacherPreference.teacher_id==preference.teacher_id,
        TeacherPreference.status=="accepted",
        TeacherPreference.id!=preference.id,
    )).all()

    # Thử đồng thời cập nhật trạng thái và xếp lại lịch trong savepoint. Nếu
    # không thể thỏa ràng buộc cứng, toàn bộ trạng thái được khôi phục.
    schedule_attempt=db.begin_nested()
    try:
        for row in previous:
            row.status="superseded"
        preference.status="accepted"
        preference.reviewed_at=datetime.now().isoformat(timespec="seconds")
        db.flush()

        removable=[lesson for lesson in teacher_lessons if not lesson.locked]
        for lesson in removable:
            db.delete(lesson)
        db.flush()

        result=solve_missing(db,p,tries=240,target_assignment_ids=assignment_ids)
        locked_slots_by_assignment=defaultdict(list)
        for lesson in teacher_lessons:
            if lesson.locked:
                locked_slots_by_assignment[lesson.assignment_id].append(lesson.slot)
        result_slots=defaultdict(list)
        for assignment_id,slot,_locked in result["lessons"]:
            result_slots[assignment_id].append(slot)

        final_slots={
            assignment.id:[*locked_slots_by_assignment[assignment.id],*result_slots[assignment.id]]
            for assignment in teacher_assignments
        }
        new_assignment_valid=(
            result.get("unscheduled",0)==0
            and not result.get("invalid_assignments")
            and all(
                len(final_slots[assignment.id])==assignment.periods_per_week
                and assignment_pattern_matches(p,assignment,final_slots[assignment.id])
                and all(slot not in unavailable for slot in final_slots[assignment.id])
                for assignment in teacher_assignments
            )
        )
        new_cost=preference_cost(
            slot for assignment in teacher_assignments for slot in final_slots[assignment.id]
        )
        should_apply=new_assignment_valid and (
            not old_assignment_valid or not old_hard_valid or new_cost<old_cost
        )

        if should_apply:
            add_generated_lessons(db,p,result["lessons"])
            db.flush()
            schedule_attempt.commit()
            db.commit()
            moved=added=removed_count=0
            for assignment in teacher_assignments:
                old_set=set(original_slots[assignment.id])
                new_set=set(final_slots[assignment.id])
                removed_here=len(old_set-new_set)
                added_here=len(new_set-old_set)
                moved_here=min(removed_here,added_here)
                moved+=moved_here
                added+=added_here-moved_here
                removed_count+=removed_here-moved_here
            changed=moved+added+removed_count
            details=[]
            if moved: details.append(f"di chuyển {moved}")
            if added: details.append(f"bổ sung {added}")
            if removed_count: details.append(f"loại bỏ {removed_count}")
            detail_text=f" ({', '.join(details)})" if details else ""
            return {
                "ok":True,
                "message":f"Đã duyệt nguyện vọng và điều chỉnh {changed} tiết{detail_text}. Các tiết cần tránh hiện là ràng buộc cứng.",
            }

        schedule_attempt.rollback()
        if old_assignment_valid and old_hard_valid:
            for row in previous:
                row.status="superseded"
            preference.status="accepted"
            preference.reviewed_at=datetime.now().isoformat(timespec="seconds")
            db.commit()
            return {
                "ok":True,
                "message":"Đã duyệt nguyện vọng. Lịch hiện tại đã thỏa toàn bộ tiết cần tránh nên không cần di chuyển tiết học.",
            }

        db.commit()
        return JSONResponse({
            "ok":False,
            "message":"Không thể duyệt nguyện vọng vì chưa tìm được lịch đầy đủ thỏa toàn bộ tiết cần tránh. Nguyện vọng vẫn ở trạng thái chờ duyệt.",
        },409)
    except Exception:
        if schedule_attempt.is_active:
            schedule_attempt.rollback()
        db.rollback()
        raise

@app.get("/projects/{pid}/export.csv", include_in_schema=False)
def export_csv_legacy(pid:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    get_project(pid,user,db)
    return RedirectResponse(f"/projects/{pid}/export.xlsx",303)

@app.get("/projects/{pid}/export.xlsx")
def export_excel(pid:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    from app.excel_export import build_timetable_workbook

    p=get_project(pid,user,db)
    data=project_data(db,p)
    workbook=build_timetable_workbook(p,data)

    output=io.BytesIO()
    workbook.save(output)
    output.seek(0)
    encoded_filename=quote(f"{p.name}.xlsx",safe="")
    disposition=f"attachment; filename=thoi-khoa-bieu.xlsx; filename*=UTF-8''{encoded_filename}"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":disposition},
    )

def project_data(db:Session,p:Project):
    deps=db.scalars(select(Department).where(Department.project_id==p.id)).all()
    subs=db.scalars(select(Subject).where(Subject.project_id==p.id)).all()
    teas=db.scalars(select(Teacher).where(Teacher.project_id==p.id)).all()
    grades=db.scalars(select(Grade).where(Grade.project_id==p.id)).all()
    grade_requirements=db.scalars(select(GradeSubjectRequirement).where(GradeSubjectRequirement.project_id==p.id)).all()
    classes=db.scalars(select(SchoolClass).where(SchoolClass.project_id==p.id)).all()
    assignments=db.scalars(select(Assignment).where(Assignment.project_id==p.id)).all()
    lessons=db.scalars(select(Lesson).where(Lesson.project_id==p.id)).all()
    sm={x.id:x for x in subs};tm={x.id:x for x in teas};cm={x.id:x for x in classes}
    teacher_subject_rows=db.scalars(select(TeacherSubject).where(TeacherSubject.project_id==p.id)).all()
    teacher_subject_map=defaultdict(list)
    for row in teacher_subject_rows:
        teacher_subject_map[row.teacher_id].append(row.subject_id)
    teacher_loads=Counter()
    for assignment in assignments:
        teacher_loads[assignment.teacher_id]+=assignment.periods_per_week
    _preferred,accepted_unavailable=accepted_teacher_preferences(db,p.id)
    capacity_issues=schedule_teacher_capacity_issues(db,p,assignments)
    class_capacity_issues=schedule_class_capacity_issues(p,classes,assignments)
    duplicate_issues=duplicate_assignment_issues(db,assignments)
    assigned_teacher_ids={x.teacher_id for x in assignments};assigned_subject_ids={x.subject_id for x in assignments};assigned_class_ids={x.class_id for x in assignments}
    return {
      "project":{"id":p.id,"name":p.name,"school_name":p.school_name,"days":p.days,"sessions":p.sessions,"periods":p.periods_per_session,"share_token":p.share_token,"blocked_slots":valid_slots(p,parse_slots(p.blocked_slots_json),strict=False)},
      "departments":[{"id":x.id,"name":x.name} for x in deps],
      "subjects":[{"id":x.id,"name":x.name,"short_name":x.short_name,"max_consecutive":x.max_consecutive} for x in subs],
      "teachers":[{"id":x.id,"name":x.name,"short_name":x.short_name,"department_id":x.department_id,"max_periods_day":x.max_periods_day,"unavailable":list(parse_slots(x.unavailable_json)),"subject_ids":sorted(teacher_subject_map.get(x.id,[])),"assigned_periods":teacher_loads.get(x.id,0),"week_capacity":teacher_week_capacity(p,x,extra_unavailable=accepted_unavailable.get(x.id,set()))} for x in teas],
      "grades":[{"id":x.id,"name":x.name} for x in grades],
      "grade_requirements":[{
          "id":x.id,"grade_id":x.grade_id,"subject_id":x.subject_id,
          "periods_per_week":x.periods_per_week,"block_mode":x.block_mode,
      } for x in grade_requirements],
      "classes":[{"id":x.id,"name":x.name,"grade_id":x.grade_id,"unavailable":list(parse_slots(x.unavailable_json))} for x in classes],
      "assignments":[{"id":x.id,"class_id":x.class_id,"subject_id":x.subject_id,"teacher_id":x.teacher_id,"periods_per_week":x.periods_per_week,"block_mode":x.block_mode,"class_name":cm.get(x.class_id).name if cm.get(x.class_id) else "?","subject_name":sm.get(x.subject_id).name if sm.get(x.subject_id) else "?","subject_short":sm.get(x.subject_id).short_name if sm.get(x.subject_id) else "?","teacher_name":tm.get(x.teacher_id).name if tm.get(x.teacher_id) else "?","teacher_short":tm.get(x.teacher_id).short_name if tm.get(x.teacher_id) else "?"} for x in assignments],
      "lessons":[{"id":x.id,"assignment_id":x.assignment_id,"slot":x.slot,"locked":x.locked} for x in lessons],
      "coverage":{
        "duplicate_assignments":duplicate_issues,
        "over_capacity_teachers":capacity_issues,
        "over_capacity_classes":class_capacity_issues,
        "unassigned_teachers":[{"id":x.id,"name":x.name} for x in teas if x.id not in assigned_teacher_ids],
        "unassigned_subjects":[{"id":x.id,"name":x.name} for x in subs if x.id not in assigned_subject_ids],
        "unassigned_classes":[{"id":x.id,"name":x.name} for x in classes if x.id not in assigned_class_ids],
      }
    }

def public_project_data(db:Session,p:Project):
    subjects={x.id:x for x in db.scalars(select(Subject).where(Subject.project_id==p.id)).all()}
    teachers={x.id:x for x in db.scalars(select(Teacher).where(Teacher.project_id==p.id)).all()}
    classes={x.id:x for x in db.scalars(select(SchoolClass).where(SchoolClass.project_id==p.id)).all()}
    assignments=db.scalars(select(Assignment).where(Assignment.project_id==p.id)).all()
    lessons=db.scalars(select(Lesson).where(Lesson.project_id==p.id)).all()
    return {
        "project":{
            "id":p.id,"name":p.name,"school_name":p.school_name,"days":p.days,
            "sessions":p.sessions,"periods":p.periods_per_session,
        },
        "classes":[{"id":item.id,"name":item.name} for item in classes.values()],
        "teachers":[{"id":item.id,"name":item.name,"short_name":item.short_name} for item in teachers.values()],
        "subjects":[{"id":item.id,"name":item.name,"short_name":item.short_name} for item in subjects.values()],
        "assignments":[{
            "id":item.id,"class_id":item.class_id,"subject_id":item.subject_id,"teacher_id":item.teacher_id,
            "periods_per_week":item.periods_per_week,"block_mode":item.block_mode,
            "class_name":classes[item.class_id].name if item.class_id in classes else "?",
            "subject_name":subjects[item.subject_id].name if item.subject_id in subjects else "?",
            "subject_short":subjects[item.subject_id].short_name if item.subject_id in subjects else "?",
            "teacher_name":teachers[item.teacher_id].name if item.teacher_id in teachers else "?",
            "teacher_short":teachers[item.teacher_id].short_name if item.teacher_id in teachers else "?",
        } for item in assignments],
        "lessons":[{"id":item.id,"assignment_id":item.assignment_id,"slot":item.slot} for item in lessons],
    }

def ga_schedule(db:Session,p:Project,mode:str,tries:int=120,target_assignment_ids:Optional[set[int]]=None):
    assignments=db.scalars(select(Assignment).where(Assignment.project_id==p.id)).all()
    teachers={x.id:x for x in db.scalars(select(Teacher).where(Teacher.project_id==p.id))}
    classes={x.id:x for x in db.scalars(select(SchoolClass).where(SchoolClass.project_id==p.id))}
    subjects={x.id:x for x in db.scalars(select(Subject).where(Subject.project_id==p.id))}
    all_existing=db.scalars(select(Lesson).where(Lesson.project_id==p.id)).all()
    if mode=="missing":
        existing=list(all_existing)
    elif mode=="rebuild":
        existing=[lesson for lesson in all_existing if lesson.locked]
    elif mode=="full":
        existing=[]
    else:
        raise ValueError(f"Chế độ xếp lịch không hợp lệ: {mode}")
    existing_counts=Counter(x.assignment_id for x in existing)
    existing_slots=defaultdict(set)
    locked_slots=defaultdict(set)
    for lesson in existing:
        existing_slots[lesson.assignment_id].add(lesson.slot)
        if lesson.locked:
            locked_slots[lesson.assignment_id].add(lesson.slot)
    fixed_rows_by_assignment=defaultdict(list)
    for row in db.scalars(select(FixedLesson).where(FixedLesson.project_id==p.id)).all():
        assignment=next((item for item in assignments if item.id==row.assignment_id),None)
        if assignment:
            size=fixed_row_size(p,assignment,row,[lesson for lesson in all_existing if lesson.assignment_id==assignment.id])
            fixed_rows_by_assignment[row.assignment_id].append((row.slot,size))
    invalid_fixed_assignment_ids=set()
    for assignment in assignments:
        fixed_error=fixed_group_validation_error(
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
    requested_preferred,requested_unavailable=accepted_teacher_preferences(db,p.id)
    global_blocked=parse_slots(p.blocked_slots_json)
    slots=all_slots(p)
    ppd=p.sessions*p.periods_per_session
    if not assignments:
        return {"lessons":[],"unscheduled":0,"score":0}

    task_rows=[]
    invalid_assignment_ids=[]
    for assignment in assignments:
        if target_assignment_ids is not None and assignment.id not in target_assignment_ids:
            continue
        if assignment.id in invalid_fixed_assignment_ids:
            continue
        current_slots=existing_slots[assignment.id] if mode in {"missing","rebuild"} else set()
        plan=pattern_completion_plan(p,assignment,current_slots)
        if plan is None:
            invalid_assignment_ids.append(assignment.id)
            continue
        pending=[dict(item) for item in plan]
        task_index=0
        for fixed_slot,fixed_size in fixed_rows_by_assignment[assignment.id]:
            expected=set(range(fixed_slot,fixed_slot+fixed_size))
            if expected.issubset(locked_slots[assignment.id]):
                continue

            # Một cụm cố định có thể chỉ còn lại một phần trên lịch. Khi đó
            # pattern_completion_plan() trả về task có anchor_slots. Task này
            # vẫn phải bị ép về đúng đầu cụm FixedLesson, thay vì được solver
            # coi là một cụm thường và chọn đầu khác.
            item=pop_matching_fixed_task(pending,fixed_slot,fixed_size)
            if item is None:
                invalid_fixed_assignment_ids.add(assignment.id)
                break
            task_rows.append((
                assignment,
                task_index,
                fixed_size,
                assignment_requires_double(assignment),
                fixed_slot,
                tuple(item["anchor_slots"]),
                (fixed_slot,),
            ))
            task_index+=1
        if assignment.id in invalid_fixed_assignment_ids:
            continue
        for item in pending:
            task_rows.append((
                assignment,
                task_index,
                item["size"],
                assignment_requires_double(assignment),
                None,
                tuple(item["anchor_slots"]),
                item["candidate_starts"],
            ))
            task_index+=1

    if invalid_assignment_ids or invalid_fixed_assignment_ids:
        affected_ids=set(invalid_assignment_ids).union(invalid_fixed_assignment_ids)
        missing=sum(
            max(0,assignment.periods_per_week-len(existing_slots[assignment.id]))
            for assignment in assignments if assignment.id in affected_ids
        )
        if invalid_fixed_assignment_ids and missing==0:
            missing=len(invalid_fixed_assignment_ids)
        return {
            "lessons":[],"unscheduled":missing,"score":missing*10000,
            "invalid_assignments":invalid_assignment_ids,
            "invalid_fixed_assignments":sorted(invalid_fixed_assignment_ids),
        }

    if not task_rows:
        return {"lessons":[],"unscheduled":0,"score":0}

    random.shuffle(task_rows)
    task_rows.sort(key=lambda task:(
        1 if task[4] is not None else 0,
        task[2]-len(task[5]),
        len(parse_slots(teachers[task[0].teacher_id].unavailable_json))+len(parse_slots(classes[task[0].class_id].unavailable_json)),
        -existing_counts[task[0].id],
    ),reverse=True)

    def valid_start_slots(size:int):
        return [slot for slot in slots if (slot % ppd) % p.periods_per_session + size <= p.periods_per_session]

    starts_by_size={}
    def start_pool(size:int):
        pool=starts_by_size.get(size)
        if pool is None:
            pool=valid_start_slots(size)
            starts_by_size[size]=pool
        return pool

    def evaluate(genes:list[int|None]):
        teacher_busy=defaultdict(set)
        class_busy=defaultdict(set)
        assignment_busy=defaultdict(set)
        teacher_day=Counter()
        class_sub_day=Counter()
        class_sub_slots=defaultdict(set)
        placed=[]
        chosen_starts=[None]*len(task_rows)
        unscheduled=0
        gene_miss=0.0
        preference_score=0.0

        for lesson in existing:
            assignment=next((x for x in assignments if x.id==lesson.assignment_id),None)
            if not assignment:
                continue
            day=lesson.slot//ppd
            teacher_busy[assignment.teacher_id].add(lesson.slot)
            class_busy[assignment.class_id].add(lesson.slot)
            assignment_busy[assignment.id].add(lesson.slot)
            teacher_day[(assignment.teacher_id,day)]+=1
            class_sub_day[(assignment.class_id,assignment.subject_id,day)]+=1
            class_sub_slots[(assignment.class_id,assignment.subject_id,day)].add(lesson.slot%ppd)

        for index,task in enumerate(task_rows):
            assignment,group_index,size,explicit,forced,anchor_slots,planned_starts=task
            anchor=set(anchor_slots)
            missing_size=size-len(anchor)
            gene=forced if forced is not None else genes[index]
            if forced is not None:
                candidate_pool=[forced]
            elif planned_starts is not None:
                candidate_pool=list(planned_starts)
            else:
                candidate_pool=start_pool(size)
            tu=parse_slots(teachers[assignment.teacher_id].unavailable_json)
            requested_avoid=requested_unavailable.get(assignment.teacher_id,set())
            preferred=requested_preferred.get(assignment.teacher_id,set())
            cu=parse_slots(classes[assignment.class_id].unavailable_json)

            def soft_preference_score(candidate_slots):
                value=0.0
                if preferred:
                    value+=sum(-4 if candidate in preferred else 1.5 for candidate in candidate_slots)
                return value
            best_slot=None
            best_score=None
            for slot in candidate_pool:
                if slot is None or slot not in slots:
                    continue
                day=slot//ppd
                position=slot%ppd
                session=position//p.periods_per_session
                period=position%p.periods_per_session
                if period+size>p.periods_per_session:
                    continue
                group_slots=list(range(slot,slot+size))
                group_set=set(group_slots)
                if anchor and not anchor.issubset(group_set):
                    continue
                new_slots=[candidate for candidate in group_slots if candidate not in anchor]
                if len(new_slots)!=missing_size:
                    continue
                if any(candidate//ppd!=day or (candidate%ppd)//p.periods_per_session!=session for candidate in group_slots):
                    continue
                if any(candidate in global_blocked or candidate in tu or candidate in requested_avoid or candidate in cu or candidate in teacher_busy[assignment.teacher_id] or candidate in class_busy[assignment.class_id] for candidate in new_slots):
                    continue
                if teacher_day[(assignment.teacher_id,day)]+missing_size>teachers[assignment.teacher_id].max_periods_day:
                    continue
                if explicit:
                    neighbors=[]
                    if period>0:
                        neighbors.append(slot-1)
                    if period+size<p.periods_per_session:
                        neighbors.append(slot+size)
                    if any(neighbor in assignment_busy[assignment.id] for neighbor in neighbors):
                        continue
                existing_periods=[
                    candidate%p.periods_per_session
                    for candidate in class_sub_slots[(assignment.class_id,assignment.subject_id,day)]
                    if candidate//p.periods_per_session==session
                ]
                run=sorted(set(existing_periods+list(range(period,period+size))))
                longest=current=1
                for left,right in zip(run,run[1:]):
                    current=current+1 if right==left+1 else 1
                    longest=max(longest,current)
                if longest>subjects[assignment.subject_id].max_consecutive:
                    continue
                score=class_sub_day[(assignment.class_id,assignment.subject_id,day)]*8+sum((candidate%p.periods_per_session)*0.15 for candidate in new_slots)
                score+=soft_preference_score(new_slots)
                neighbors=[]
                if period>0:
                    neighbors.append(slot-1)
                if period+size<p.periods_per_session:
                    neighbors.append(slot+size)
                for neighbor in neighbors:
                    if neighbor in teacher_busy[assignment.teacher_id]:
                        score-=1.2
                    if assignment_prefers_double(assignment) and neighbor in assignment_busy[assignment.id]:
                        score-=7.0
                if gene is not None:
                    if slot==gene:
                        score-=8
                    else:
                        score+=abs(slot-gene)*0.05
                if best_score is None or score<best_score:
                    best_score=score
                    best_slot=slot
            if best_slot is None:
                unscheduled+=missing_size
                continue
            chosen_starts[index]=best_slot
            day=best_slot//ppd
            gene_value=forced if forced is not None else genes[index]
            if gene_value is not None and best_slot!=gene_value:
                gene_miss+=abs(best_slot-gene_value)
            for slot in range(best_slot,best_slot+size):
                if slot in anchor:
                    continue
                teacher_busy[assignment.teacher_id].add(slot)
                class_busy[assignment.class_id].add(slot)
                assignment_busy[assignment.id].add(slot)
                class_sub_slots[(assignment.class_id,assignment.subject_id,day)].add(slot%ppd)
                placed.append((assignment.id,slot,forced is not None))
            teacher_day[(assignment.teacher_id,day)]+=missing_size
            class_sub_day[(assignment.class_id,assignment.subject_id,day)]+=missing_size
            preference_score+=soft_preference_score(
                [slot for slot in range(best_slot,best_slot+size) if slot not in anchor]
            )

        score=unscheduled*10000+gene_miss*0.05+preference_score
        for (cid,sid,day),n in class_sub_day.items():
            score+=max(0,n-1)*10
        for tid,busy in teacher_busy.items():
            for day in range(p.days):
                xs=sorted(slot%ppd for slot in busy if slot//ppd==day)
                if xs:
                    score+=(xs[-1]-xs[0]+1-len(xs))*2
        for assignment in assignments:
            if not assignment_prefers_double(assignment):
                continue
            runs=assignment_run_groups(p,assignment_busy[assignment.id])
            formed_pairs=sum(run["size"]//2 for run in runs)
            target_pairs=assignment.periods_per_week//2
            score+=max(0,target_pairs-formed_pairs)*14
        return {"lessons":placed,"unscheduled":unscheduled,"score":round(score,2),"genes":chosen_starts}

    def genes_from_candidate(candidate):
        genes=list(candidate.get("genes",[]))
        if len(genes)!=len(task_rows):
            genes=[None]*len(task_rows)
        return genes

    def random_gene(task):
        assignment,group_index,size,explicit,forced,anchor_slots,planned_starts=task
        if forced is not None:
            return forced
        pool=list(planned_starts) if planned_starts is not None else start_pool(size)
        return random.choice(pool) if pool else None

    def mutate(genes):
        child=genes[:]
        for index,task in enumerate(task_rows):
            assignment,group_index,size,explicit,forced,anchor_slots,planned_starts=task
            if forced is not None:
                child[index]=forced
                continue
            if random.random()<0.15:
                child[index]=random_gene(task) if random.random()<0.9 else None
        return child

    def crossover(left,right):
        child=[]
        for index,task in enumerate(task_rows):
            assignment,group_index,size,explicit,forced,anchor_slots,planned_starts=task
            if forced is not None:
                child.append(forced)
            elif random.random()<0.5:
                child.append(left[index])
            else:
                child.append(right[index])
        return child

    def exact_fallback(node_limit:int):
        """Thử tìm lời giải đầy đủ bằng backtracking cho bài toán vừa/nhỏ.

        GA vẫn được dùng trước để có tốc độ tốt. Khi GA bỏ sót lời giải, bước
        này duyệt có hệ thống và có thể chứng minh vô nghiệm nếu hoàn tất toàn
        bộ cây tìm kiếm trước giới hạn nút.
        """
        teacher_busy=defaultdict(set)
        class_busy=defaultdict(set)
        assignment_busy=defaultdict(set)
        teacher_day=Counter()
        class_sub_day=Counter()
        class_sub_slots=defaultdict(set)
        for lesson in existing:
            assignment=next((x for x in assignments if x.id==lesson.assignment_id),None)
            if not assignment:
                continue
            day=lesson.slot//ppd
            teacher_busy[assignment.teacher_id].add(lesson.slot)
            class_busy[assignment.class_id].add(lesson.slot)
            assignment_busy[assignment.id].add(lesson.slot)
            teacher_day[(assignment.teacher_id,day)]+=1
            class_sub_day[(assignment.class_id,assignment.subject_id,day)]+=1
            class_sub_slots[(assignment.class_id,assignment.subject_id,day)].add(lesson.slot%ppd)

        raw_candidates=[]
        for task in task_rows:
            assignment,group_index,size,explicit,forced,anchor_slots,planned_starts=task
            if forced is not None:
                pool=[forced]
            elif planned_starts is not None:
                pool=list(planned_starts)
            else:
                pool=start_pool(size)
            raw_candidates.append([slot for slot in pool if slot is not None])

        placed_by_task={}
        remaining=set(range(len(task_rows)))
        nodes=0
        limit_hit=False

        def options_for(index:int):
            assignment,group_index,size,explicit,forced,anchor_slots,planned_starts=task_rows[index]
            anchor=set(anchor_slots)
            missing_size=size-len(anchor)
            tu=parse_slots(teachers[assignment.teacher_id].unavailable_json)
            requested_avoid=requested_unavailable.get(assignment.teacher_id,set())
            preferred=requested_preferred.get(assignment.teacher_id,set())
            cu=parse_slots(classes[assignment.class_id].unavailable_json)
            options=[]
            for slot in raw_candidates[index]:
                if slot not in slots:
                    continue
                day=slot//ppd
                position=slot%ppd
                session=position//p.periods_per_session
                period=position%p.periods_per_session
                if period+size>p.periods_per_session:
                    continue
                group_slots=tuple(range(slot,slot+size))
                group_set=set(group_slots)
                if anchor and not anchor.issubset(group_set):
                    continue
                new_slots=tuple(candidate for candidate in group_slots if candidate not in anchor)
                if len(new_slots)!=missing_size:
                    continue
                if any(candidate//ppd!=day or (candidate%ppd)//p.periods_per_session!=session for candidate in group_slots):
                    continue
                if any(candidate in global_blocked or candidate in tu or candidate in requested_avoid or candidate in cu or candidate in teacher_busy[assignment.teacher_id] or candidate in class_busy[assignment.class_id] for candidate in new_slots):
                    continue
                if teacher_day[(assignment.teacher_id,day)]+missing_size>teachers[assignment.teacher_id].max_periods_day:
                    continue
                if explicit:
                    neighbors=[]
                    if period>0:
                        neighbors.append(slot-1)
                    if period+size<p.periods_per_session:
                        neighbors.append(slot+size)
                    if any(neighbor in assignment_busy[assignment.id] for neighbor in neighbors):
                        continue
                existing_periods=[
                    candidate%p.periods_per_session
                    for candidate in class_sub_slots[(assignment.class_id,assignment.subject_id,day)]
                    if candidate//p.periods_per_session==session
                ]
                run=sorted(set(existing_periods+list(range(period,period+size))))
                longest=current=1
                for left,right in zip(run,run[1:]):
                    current=current+1 if right==left+1 else 1
                    longest=max(longest,current)
                if longest>subjects[assignment.subject_id].max_consecutive:
                    continue
                preference_cost=sum(-4 if candidate in preferred else 1.5 for candidate in new_slots) if preferred else 0
                adjacent_same=0
                if assignment_prefers_double(assignment):
                    if period>0 and slot-1 in assignment_busy[assignment.id]:
                        adjacent_same+=1
                    if period+size<p.periods_per_session and slot+size in assignment_busy[assignment.id]:
                        adjacent_same+=1
                score=(
                    class_sub_day[(assignment.class_id,assignment.subject_id,day)]*8
                    +sum((candidate%p.periods_per_session)*0.15 for candidate in new_slots)
                    +preference_cost
                    -adjacent_same*7
                )
                options.append((score,slot,group_slots,new_slots,day))
            options.sort(key=lambda item:(item[0],item[1]))
            return options

        def apply(index:int,option):
            _score,slot,group_slots,new_slots,day=option
            assignment,group_index,size,explicit,forced,anchor_slots,planned_starts=task_rows[index]
            for candidate in new_slots:
                teacher_busy[assignment.teacher_id].add(candidate)
                class_busy[assignment.class_id].add(candidate)
                assignment_busy[assignment.id].add(candidate)
                class_sub_slots[(assignment.class_id,assignment.subject_id,day)].add(candidate%ppd)
            teacher_day[(assignment.teacher_id,day)]+=len(new_slots)
            class_sub_day[(assignment.class_id,assignment.subject_id,day)]+=len(new_slots)
            placed_by_task[index]=(assignment.id,tuple(new_slots),forced is not None)

        def undo(index:int,option):
            _score,slot,group_slots,new_slots,day=option
            assignment,group_index,size,explicit,forced,anchor_slots,planned_starts=task_rows[index]
            placed_by_task.pop(index,None)
            teacher_day[(assignment.teacher_id,day)]-=len(new_slots)
            class_sub_day[(assignment.class_id,assignment.subject_id,day)]-=len(new_slots)
            for candidate in new_slots:
                teacher_busy[assignment.teacher_id].remove(candidate)
                class_busy[assignment.class_id].remove(candidate)
                assignment_busy[assignment.id].remove(candidate)
                class_sub_slots[(assignment.class_id,assignment.subject_id,day)].remove(candidate%ppd)

        def search():
            nonlocal nodes,limit_hit
            if not remaining:
                return True
            nodes+=1
            if nodes>node_limit:
                limit_hit=True
                return False
            selected_index=None
            selected_options=None
            for index in tuple(remaining):
                options=options_for(index)
                if not options:
                    return False
                if selected_options is None or len(options)<len(selected_options):
                    selected_index=index
                    selected_options=options
                    if len(options)==1:
                        break
            remaining.remove(selected_index)
            for option in selected_options:
                apply(selected_index,option)
                if search():
                    return True
                undo(selected_index,option)
                if limit_hit:
                    break
            remaining.add(selected_index)
            return False

        solved=search()
        if not solved:
            return None,not limit_hit,nodes
        lessons=[]
        for index in range(len(task_rows)):
            assignment_id,new_slots,locked=placed_by_task[index]
            lessons.extend((assignment_id,slot,locked) for slot in new_slots)
        preference_score=0.0
        final_slots=defaultdict(set)
        for lesson in existing:
            final_slots[lesson.assignment_id].add(lesson.slot)
        for assignment_id,slot,_locked in lessons:
            final_slots[assignment_id].add(slot)
            assignment=next(item for item in assignments if item.id==assignment_id)
            preferred=requested_preferred.get(assignment.teacher_id,set())
            if preferred:
                preference_score+=-4 if slot in preferred else 1.5
        for assignment in assignments:
            if assignment_prefers_double(assignment):
                formed_pairs=sum(run["size"]//2 for run in assignment_run_groups(p,final_slots[assignment.id]))
                preference_score+=max(0,assignment.periods_per_week//2-formed_pairs)*14
        return {
            "lessons":lessons,
            "unscheduled":0,
            "score":round(preference_score,2),
            "exact":True,
        },True,nodes

    # Quy mô cũ dừng ở 40×60 nên các project vừa/lớn dễ hết lượt trước khi
    # tìm thấy nghiệm. Vẫn giữ trần hữu hạn để request không chạy vô hạn.
    population_size=max(24,min(56,max(18,len(task_rows))))
    generations=max(18,min(75,max(tries//3,24)))
    elite_count=max(2,population_size//5)

    seed_candidate=evaluate([None]*len(task_rows))
    best_candidate=seed_candidate
    population=[genes_from_candidate(seed_candidate)]
    for _ in range(population_size-1):
        population.append([random_gene(task) for task in task_rows])

    evaluated=[]
    for genes in population:
        candidate=evaluate(genes)
        evaluated.append((candidate,genes))
        if candidate["score"]<best_candidate["score"]:
            best_candidate=candidate

    for _ in range(generations):
        evaluated.sort(key=lambda item:(item[0]["score"],item[0]["unscheduled"]))
        elites=[genes for _candidate,genes in evaluated[:elite_count]]
        if evaluated[0][0]["score"]<best_candidate["score"]:
            best_candidate=evaluated[0][0]
        next_population=elites[:]
        while len(next_population)<population_size:
            pool=evaluated[:max(6,population_size//2)]
            parent1=random.choice(pool)[1]
            parent2=random.choice(pool)[1]
            child=mutate(crossover(parent1,parent2))
            next_population.append(child)
        evaluated=[]
        for genes in next_population:
            candidate=evaluate(genes)
            evaluated.append((candidate,genes))
            if candidate["score"]<best_candidate["score"]:
                best_candidate=candidate

    if evaluated:
        evaluated.sort(key=lambda item:(item[0]["score"],item[0]["unscheduled"]))
        if evaluated[0][0]["score"]<best_candidate["score"]:
            best_candidate=evaluated[0][0]

    if best_candidate["unscheduled"]>0:
        missing_periods=sum(task[2]-len(task[5]) for task in task_rows)
        exact_allowed=len(task_rows)<=48 and missing_periods<=60
        if exact_allowed:
            node_limit=min(750000,max(75000,tries*2000))
            exact_result,exhausted,nodes=exact_fallback(node_limit)
            if exact_result is not None:
                return exact_result
            best_candidate["proven_infeasible"]=exhausted
            best_candidate["search_limited"]=not exhausted
            best_candidate["exact_nodes"]=nodes
        else:
            best_candidate["proven_infeasible"]=False
            best_candidate["search_limited"]=True
    return best_candidate

def solve_missing(db:Session,p:Project,tries=120,target_assignment_ids:Optional[set[int]]=None):
    """Giữ nguyên lịch hiện có và chỉ xếp phần còn thiếu của các phân công đích."""
    return ga_schedule(
        db,p,mode="missing",tries=tries,
        target_assignment_ids=target_assignment_ids,
    )

def solve_rebuild(db:Session,p:Project,tries=220):
    """Giữ tiết cố định, xếp lại toàn bộ phần còn lại."""
    return ga_schedule(db,p,mode="rebuild",tries=tries)


def solve(db:Session,p:Project,tries=80):
    return ga_schedule(db,p,mode="full",tries=tries)

def seed_project(db:Session,p:Project):
    d1=Department(project_id=p.id,name="Tổ Toán - Tin");d2=Department(project_id=p.id,name="Tổ Ngữ văn")
    db.add_all([d1,d2]);db.flush()
    s1=Subject(project_id=p.id,name="Toán",short_name="TOÁN",max_consecutive=2);s2=Subject(project_id=p.id,name="Ngữ văn",short_name="VĂN",max_consecutive=2);s3=Subject(project_id=p.id,name="Tin học",short_name="TIN",max_consecutive=1)
    db.add_all([s1,s2,s3]);db.flush()
    t1=Teacher(project_id=p.id,department_id=d1.id,name="Nguyễn Văn An",short_name="An",max_periods_day=4);t2=Teacher(project_id=p.id,department_id=d2.id,name="Trần Thị Bình",short_name="Bình",max_periods_day=4);t3=Teacher(project_id=p.id,department_id=d1.id,name="Lê Minh Châu",short_name="Châu",max_periods_day=4)
    db.add_all([t1,t2,t3]);db.flush()
    db.add_all([
        TeacherSubject(project_id=p.id,teacher_id=t1.id,subject_id=s1.id),
        TeacherSubject(project_id=p.id,teacher_id=t2.id,subject_id=s2.id),
        TeacherSubject(project_id=p.id,teacher_id=t3.id,subject_id=s3.id),
    ])
    g=Grade(project_id=p.id,name="Khối 10");db.add(g);db.flush()
    c1=SchoolClass(project_id=p.id,grade_id=g.id,name="10A1");c2=SchoolClass(project_id=p.id,grade_id=g.id,name="10A2");db.add_all([c1,c2]);db.flush()
    for c in [c1,c2]:
        db.add_all([Assignment(project_id=p.id,class_id=c.id,subject_id=s1.id,teacher_id=t1.id,periods_per_week=4),Assignment(project_id=p.id,class_id=c.id,subject_id=s2.id,teacher_id=t2.id,periods_per_week=3),Assignment(project_id=p.id,class_id=c.id,subject_id=s3.id,teacher_id=t3.id,periods_per_week=2)])
    db.commit()

def ensure_demo():
    db=SessionLocal()
    try:
        existing_admin = db.scalar(select(User.id).where(User.role.in_(ADMIN_ROLES)).limit(1))
        if SUPER_ADMIN_USER_ID > 0:
            existing_bootstrap = db.get(User, SUPER_ADMIN_USER_ID)
        else:
            existing_bootstrap = db.scalar(
                select(User).where(func.lower(User.email) == BOOTSTRAP_ADMIN_EMAIL).limit(1)
            ) if BOOTSTRAP_ADMIN_EMAIL else None
        if existing_bootstrap and existing_bootstrap.role == "super_admin":
            return
        if not BOOTSTRAP_ADMIN_EMAIL or len(BOOTSTRAP_ADMIN_PASSWORD) < 8:
            if existing_admin is not None:
                return
            raise RuntimeError(
                "Database chưa có quản trị viên. Hãy cấu hình BOOTSTRAP_ADMIN_EMAIL và "
                "BOOTSTRAP_ADMIN_PASSWORD (ít nhất 8 ký tự) trong .env để khôi phục quyền quản trị."
            )

        # Nếu email bootstrap đã tồn tại, nâng chính tài khoản đó lên admin
        # thay vì tạo user trùng email. Áp dụng mật khẩu bootstrap để chủ hệ
        # thống chắc chắn có thể đăng nhập lại và tăng session_version để vô
        # hiệu hóa các phiên cũ của tài khoản vừa được khôi phục.
        user = existing_bootstrap
        if user is None:
            user=User(
                email=BOOTSTRAP_ADMIN_EMAIL,
                name="Quản trị viên",
                password_hash=pwd.hash(BOOTSTRAP_ADMIN_PASSWORD),
                role="super_admin",
                is_superadmin=True,
            )
            db.add(user)
        else:
            for link in db.scalars(
                select(TeacherAccountLink).where(TeacherAccountLink.user_id == user.id)
            ).all():
                db.delete(link)
            clear_teacher_identity(user)
            user.role = "super_admin"
            user.is_superadmin = True
            user.password_hash = pwd.hash(BOOTSTRAP_ADMIN_PASSWORD)
            user.session_version = max(1, user.session_version or 1) + 1
            if not (user.name or "").strip():
                user.name = "Quản trị viên"

        db.commit()
        if SEED_DEMO_DATA and db.scalar(select(Project.id).limit(1)) is None:
            p=Project(owner_id=user.id,name="TKB học kỳ I",school_name="THPT Demo",days=6,sessions=2,periods_per_session=5)
            db.add(p);db.commit();seed_project(db,p)
    finally:
        db.close()
ensure_demo()
