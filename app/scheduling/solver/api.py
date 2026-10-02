from __future__ import annotations

from .genetic import *


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
    """Giữ tiết cố định, xếp lại toàn bộ phần còn lại."""
    return ga_schedule(db, p, mode="rebuild", tries=tries, deadline=deadline)


def solve(db: Session, p: Project, tries=80, deadline: float | None = None):
    return ga_schedule(db, p, mode="full", tries=tries, deadline=deadline)


__all__ = [name for name in globals() if not name.startswith("__")]
