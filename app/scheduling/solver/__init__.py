"""Public scheduler API; implementations live in dedicated search modules."""
from .api import solve, solve_missing, solve_rebuild
from .engine import ga_schedule
from .scoring import _schedule_soft_score, _solver_timeout_seconds, _teacher_idle_gaps

__all__ = [
    'ga_schedule', 'solve', 'solve_missing', 'solve_rebuild', '_schedule_soft_score',
    '_solver_timeout_seconds', '_teacher_idle_gaps',
]
