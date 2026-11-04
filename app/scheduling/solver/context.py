"""Request-wide search budget and common candidate helpers."""
from __future__ import annotations

from dataclasses import dataclass
import time


@dataclass(frozen=True, slots=True)
class SearchBudget:
    deadline: float

    def time_left(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def expired(self, reserve: float = 0.0) -> bool:
        return self.time_left() <= reserve


def genes_from_candidate(candidate: dict, task_count: int) -> list[int | None]:
    genes = list(candidate.get("genes", []))
    return genes if len(genes) == task_count else [None] * task_count


def candidate_key(candidate: dict) -> tuple:
    """Missing periods take priority over every soft preference."""
    return candidate["unscheduled"], candidate["score"]
