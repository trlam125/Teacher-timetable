"""Separate metadata ensures normal Smart TKB startup never migrates Studio."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StudioBase(DeclarativeBase):
    pass


json_type = JSON().with_variant(JSONB(), "postgresql")


class Deck(StudioBase):
    __tablename__ = "ai_slide_decks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(24), default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1)
    profile: Mapped[dict] = mapped_column(json_type)
    blueprint: Mapped[dict | None] = mapped_column(json_type, nullable=True)
    manifest: Mapped[dict | None] = mapped_column(json_type, nullable=True)
    active_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    updated_at: Mapped[str] = mapped_column(String(40), default=now)


class Revision(StudioBase):
    __tablename__ = "ai_slide_revisions"
    __table_args__ = (UniqueConstraint("deck_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    deck_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(json_type)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class Step(StudioBase):
    __tablename__ = "ai_slide_steps"
    __table_args__ = (UniqueConstraint("deck_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    deck_id: Mapped[str] = mapped_column(String(36), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32))
    input_version: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(24), default="running")
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposal: Mapped[dict | None] = mapped_column(json_type, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class Quota(StudioBase):
    __tablename__ = "ai_slide_quota"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, default=0)


class Usage(StudioBase):
    __tablename__ = "ai_slide_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    deck_id: Mapped[str] = mapped_column(String(36))
    step_id: Mapped[str] = mapped_column(String(36))
    model: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(40), default=now)
