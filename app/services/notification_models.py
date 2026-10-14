"""Stored timetable notifications and immutable per-lesson change snapshots.

Import this module before ``Base.metadata.create_all`` at application startup.
The detail table is new; existing notification tables and data remain unchanged.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class ScheduleNotification(Base):
    __tablename__ = "schedule_notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    added_count: Mapped[int] = mapped_column(Integer, default=0)
    removed_count: Mapped[int] = mapped_column(Integer, default=0)
    moved_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(
        String(40),
        default=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"),
        index=True,
    )
    details: Mapped[list["ScheduleNotificationDetail"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )


class ScheduleNotificationDetail(Base):
    """A frozen snapshot; names and old positions survive later data edits."""

    __tablename__ = "schedule_notification_details"
    id: Mapped[int] = mapped_column(primary_key=True)
    notification_id: Mapped[int] = mapped_column(
        ForeignKey("schedule_notifications.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(16))
    payload_json: Mapped[str] = mapped_column(Text)


class ScheduleNotificationRead(Base):
    __tablename__ = "schedule_notification_reads"
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    notification_id: Mapped[int] = mapped_column(
        ForeignKey("schedule_notifications.id", ondelete="CASCADE"), primary_key=True
    )
    read_at: Mapped[str] = mapped_column(
        String(40),
        default=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
