"""Coordinate solvers under one deadline and keep the best valid timetable."""
from __future__ import annotations

from collections import defaultdict
from functools import partial
from typing import Optional
import time

from sqlalchemy.orm import Session

from .backtracking import exact_search
from .context import SearchBudget, candidate_key, genes_from_candidate as _candidate_genes
from .cp_sat import solve_cp_sat
from .genetic import GeneticSearch
from .problem import build_problem
from .rebuild import conflict_neighborhood, saved_placement_genes
from .repair import repair_placements
from .scoring import _schedule_soft_score, _solver_timeout_seconds
from app.models import Project


def ga_schedule(
    db: Session, p: Project, mode: str, tries: int = 120,
    target_assignment_ids: Optional[set[int]] = None, deadline: float | None = None,
):
    if deadline is None:
        deadline = time.monotonic() + _solver_timeout_seconds()
    budget = SearchBudget(deadline)
    problem = build_problem(db, p, mode, target_assignment_ids)
    if isinstance(problem, dict):
        return problem
    time_left = budget.time_left
    deadline_hit = budget.expired
    genetic = GeneticSearch(problem)
    evaluate = genetic.evaluate
    genes_from_candidate = partial(_candidate_genes, task_count=len(problem.task_rows))
    search_phases = []
    proven_infeasible = False
    cp_sat_primary = partial(solve_cp_sat, problem, budget, search_phases=search_phases)
    exact_fallback = partial(exact_search, problem, budget)
    task_rows = problem.task_rows
    task_candidates = problem.task_candidates
    all_existing = problem.all_existing
    existing = problem.existing
    assignment_by_id = problem.assignment_by_id
    assignments = problem.assignments

    seed_genes = (
        saved_placement_genes(p, task_rows, task_candidates, all_existing, existing)
        if mode == "rebuild" else [None] * len(task_rows)
    )
    seed_candidate = evaluate(seed_genes)
    seed_candidate["optimal"] = False
    best_candidate = seed_candidate
    saved_pairs = {(lesson.assignment_id, lesson.slot) for lesson in all_existing}
    reused_periods = len(existing) + sum(
        (assignment_id, slot) in saved_pairs
        for assignment_id, slot, *_ in seed_candidate["lessons"]
    )

    def finish(result):
        complete = result["unscheduled"] == 0
        result["proven_infeasible"] = not complete and bool(
            result.get("proven_infeasible") or proven_infeasible)
        result["maximum_placed"] = complete or result.get("maximum_placed", False)
        result["search_limited"] = not result["maximum_placed"]
        result["time_limit_reached"] = result["search_limited"] and deadline_hit()
        result["proof_scope"] = "retained_lessons" if mode == "missing" else "pinned_lessons"
        result["search_phases"] = search_phases
        if mode == "rebuild":
            result["reused_periods"] = reused_periods
        return result

    # Secure a valid incumbent before CP-SAT consumes the remaining budget.
    # This also supplies a complete placement hint on CPU-limited hosts.
    if best_candidate["unscheduled"] > 0 and not deadline_hit(0.05):
        repaired = repair_placements(
            task_rows, task_candidates, genes_from_candidate(best_candidate),
            existing, assignment_by_id,
            project=p,
            deadline=min(deadline, time.monotonic() + max(0.1, min(3.0, time_left() * 0.25))),
        )
        final_slots = defaultdict(set)
        for lesson in existing:
            final_slots[lesson.assignment_id].add(lesson.slot)
        for assignment_id, slot, *_ in repaired["lessons"]:
            final_slots[assignment_id].add(slot)
        repaired["score"] = repaired["unscheduled"] * 10000 + _schedule_soft_score(
            p, assignments, assignment_by_id, final_slots
        )
        repaired["optimal"] = False
        if candidate_key(repaired) < candidate_key(best_candidate):
            best_candidate = repaired

    if best_candidate["unscheduled"] == 0:
        return finish(best_candidate)

    # Use the main search to maximize coverage. Keep a small reserve for
    # relocation and fallback search when CP-SAT reaches its deadline.
    cp_result = cp_sat_primary(
        allow_partial=True, incumbent=best_candidate,
        phase_deadline=time.monotonic() + time_left() * 0.65,
    )
    proven_infeasible = bool(cp_result and cp_result.get("proven_infeasible"))
    if cp_result is not None and "genes" in cp_result:
        if candidate_key(cp_result) <= candidate_key(best_candidate):
            best_candidate = cp_result
        if cp_result.get("maximum_placed") and cp_result["unscheduled"] == best_candidate["unscheduled"]:
            best_candidate["maximum_placed"] = True
            return finish(best_candidate)

    # Local repairs retain unrelated movable lessons. They can recover a
    # handful of omissions without rebuilding the entire problem again.
    if mode in ("full", "rebuild") and not deadline_hit(0.25):
        local_deadline = time.monotonic() + time_left() * 0.5
        previous_neighborhood = None
        limits = (32, 96, 192)
        for attempt, limit in enumerate(limits):
            if time.monotonic() >= local_deadline - 0.1:
                break
            active = conflict_neighborhood(
                task_rows, task_candidates, genes_from_candidate(best_candidate), limit
            )
            neighborhood_key = (active, tuple(genes_from_candidate(best_candidate)))
            if neighborhood_key == previous_neighborhood:
                continue
            previous_neighborhood = neighborhood_key
            phase_budget = (local_deadline - time.monotonic()) / (len(limits) - attempt)
            local_result = cp_sat_primary(
                allow_partial=True, incumbent=best_candidate, neighborhood=active,
                phase_deadline=time.monotonic() + phase_budget,
            )
            if local_result is not None and "genes" in local_result:
                if candidate_key(local_result) < candidate_key(best_candidate):
                    best_candidate = local_result
                if best_candidate["unscheduled"] == 0:
                    return finish(best_candidate)

    missing_periods = sum(task[2] - len(task[5]) for task in task_rows)
    if (not proven_infeasible and len(task_rows) <= 24
            and missing_periods <= 36 and not deadline_hit(0.25)):
        node_limit = min(100000, max(20000, tries * 400))
        exact_result, exhausted, nodes = exact_fallback(node_limit)
        if exact_result is not None:
            return finish(exact_result)
        proven_infeasible = exhausted
        best_candidate["exact_nodes"] = nodes

    # Reserve time for a fresh global CP search. A different seed and the best
    # placement found so far let it explore beyond the first search trajectory.
    fallback_budget = SearchBudget(time.monotonic() + time_left() * 0.4)
    best_candidate = genetic.evolve(best_candidate, tries=tries, budget=fallback_budget, alternate=cp_result)
    if best_candidate["unscheduled"] == 0:
        return finish(best_candidate)
    if not deadline_hit(0.25):
        retry = cp_sat_primary(allow_partial=True, incumbent=best_candidate, random_seed=43)
        if retry is not None:
            proven_infeasible = proven_infeasible or retry.get("proven_infeasible", False)
            if "genes" in retry and candidate_key(retry) <= candidate_key(best_candidate):
                best_candidate = retry
            if retry.get("maximum_placed") and retry["unscheduled"] == best_candidate["unscheduled"]:
                best_candidate["maximum_placed"] = True
    return finish(best_candidate)
