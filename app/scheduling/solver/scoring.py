from __future__ import annotations

import os
from collections import Counter, defaultdict

from app.models import Assignment, Project
from app.scheduling.rules import assignment_prefers_double, preferred_double_pair_count

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
            score += max(0, target_pairs - formed_pairs) * 14

        day_counts = Counter(slot // ppd for slot in slots_for_assignment)
        score += sum(max(0, count - 1) * 8 for count in day_counts.values())

        owner = assignment_by_id.get(assignment.id)
        if owner:
            teacher_slots[owner.teacher_id].update(slots_for_assignment)

    for busy in teacher_slots.values():
        score += _teacher_idle_gaps(p, busy) * 2
    return score


def _solver_timeout_seconds() -> float:
    try:
        value = float(os.getenv("SCHEDULE_SOLVER_TIMEOUT_SECONDS", "15"))
    except (TypeError, ValueError):
        value = 15.0
    return max(3.0, min(60.0, value))


__all__ = ["_teacher_idle_gaps", "_schedule_soft_score", "_solver_timeout_seconds"]
