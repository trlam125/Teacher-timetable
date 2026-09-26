from __future__ import annotations

from datetime import datetime, timezone
import secrets
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

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
    # Persistent scheduling identity. Lessons with the same block_id are one
    # atomic scheduling block (size 2 for required_double, otherwise size 1).
    # This removes all runtime guessing based on adjacent periods.
    block_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    block_size: Mapped[int] = mapped_column(Integer, default=1)
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
