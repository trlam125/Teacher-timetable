from __future__ import annotations

from collections import Counter, defaultdict
import math
import os

from app.models import Assignment, Project
from app.scheduling.rules import assignment_prefers_double, preferred_double_pair_count

PREFERRED_DOUBLE_PENALTY = 14
SAME_DAY_PENALTY = 8
TEACHER_GAP_PENALTY = 2


def soft_score(candidate: dict) -> int:
    return int(candidate["score"] - 10000 * candidate["unscheduled"])

def _teacher_idle_gaps(p: Project, busy_slots) -> int:
    """Count idle periods inside each day/session, never across sessions."""
    ppd = p.sessions * p.periods_per_session
    busy = set(busy_slots)
    gaps = 0
    for day in range(p.days):
        day_base = day * ppd
        for session in range(p.sessions):
            start = day_base + session * p.periods_per_session
            end = start + p.periods_per_session
            periods = sorted(slot - start for slot in busy if start <= slot < end)
            if periods:
                gaps += periods[-1] - periods[0] + 1 - len(periods)
    return gaps


def _schedule_soft_score(
    p: Project,
    assignments: list[Assignment],
    assignment_by_id: dict[int, Assignment],
    final_slots: dict[int, set[int]],
) -> float:
    """One canonical soft-score formula shared by every solver.

    Lower is better. Hard feasibility is intentionally not encoded here; callers
    keep unscheduled periods as the dominant lexicographic criterion.
    """
    ppd = p.sessions * p.periods_per_session
    score = 0.0
    teacher_slots = defaultdict(set)

    for assignment in assignments:
        slots_for_assignment = set(final_slots.get(assignment.id, set()))
        if assignment_prefers_double(assignment):
            formed_pairs = preferred_double_pair_count(p, slots_for_assignment)
            target_pairs = int(assignment.periods_per_week or 0) // 2
            score += max(0, target_pairs - formed_pairs) * PREFERRED_DOUBLE_PENALTY

        day_counts = Counter(slot // ppd for slot in slots_for_assignment)
        score += sum(max(0, count - 1) for count in day_counts.values()) * SAME_DAY_PENALTY

        owner = assignment_by_id.get(assignment.id)
        if owner:
            teacher_slots[owner.teacher_id].update(slots_for_assignment)

    for busy in teacher_slots.values():
        score += _teacher_idle_gaps(p, busy) * TEACHER_GAP_PENALTY
    return score


def _timeout_seconds(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    if not math.isfinite(value):
        value = default
    return max(minimum, min(maximum, value))


def _solver_timeout_seconds() -> float:
    return _timeout_seconds("SCHEDULE_SOLVER_TIMEOUT_SECONDS", 300.0, 3.0, 3600.0)


def _quality_timeout_seconds() -> float:
    return _timeout_seconds("SCHEDULE_QUALITY_TIMEOUT_SECONDS", 30.0, 0.0, 300.0)


__all__ = [
    '_teacher_idle_gaps', '_schedule_soft_score', '_solver_timeout_seconds',
]
