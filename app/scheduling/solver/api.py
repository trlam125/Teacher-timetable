from __future__ import annotations

import time

from .genetic import *
from .scoring import _solver_timeout_seconds


def solve_missing(
    db: Session,
    p: Project,
    tries=120,
    target_assignment_ids: Optional[set[int]] = None,
    deadline: float | None = None,
):
    """Giữ nguyên lịch hiện có và chỉ xếp phần còn thiếu của các phân công đích."""
    return ga_schedule(
        db,
        p,
        mode="missing",
        tries=tries,
        target_assignment_ids=target_assignment_ids,
        deadline=deadline,
    )


def solve_rebuild(db: Session, p: Project, tries=220, deadline: float | None = None):
    """Final retry: retain pins and give the remaining search a larger budget."""
    if deadline is None:
        deadline = time.monotonic() + min(60.0, _solver_timeout_seconds() * 2)
    return ga_schedule(db, p, mode="rebuild", tries=tries, deadline=deadline)


def solve(db: Session, p: Project, tries=80, deadline: float | None = None):
    return ga_schedule(db, p, mode="full", tries=tries, deadline=deadline)


__all__ = [name for name in globals() if not name.startswith("__")]
