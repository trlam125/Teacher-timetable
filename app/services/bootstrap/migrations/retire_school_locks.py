"""Retire school-wide locks; grade and individual availability stay unchanged."""
from sqlalchemy import update

from app.models import Project


def retire_school_locks(connection):
    # Idempotent. Run after the legacy migration has ensured this column exists.
    connection.execute(
        update(Project).where(Project.blocked_slots_json != "[]").values(blocked_slots_json="[]")
    )
