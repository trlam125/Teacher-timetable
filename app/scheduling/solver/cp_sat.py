"""CP-SAT feasibility, partial placement and local repair models."""
from __future__ import annotations

from collections import defaultdict
from functools import partial
import logging
import os
import time

from .cp_sat_compact import compact_task_groups, solve_compact_cp_sat
from .cp_sat_constraints import add_subject_session_constraints
from .context import SearchBudget, genes_from_candidate as _candidate_genes
from .problem import SchedulingProblem
from .scoring import _schedule_soft_score

logger = logging.getLogger("smart_tkb")


def solve_cp_sat(
    problem: SchedulingProblem, budget: SearchBudget, allow_partial: bool = False,
    incumbent=None, *, neighborhood=None, phase_deadline=None, search_phases=None,
    random_seed=42,
):
    """Solve using the same candidates and hard constraints as the fallbacks."""
    deadline = budget.deadline
    if search_phases is None:
        search_phases = []
    genes_from_candidate = partial(_candidate_genes, task_count=len(problem.task_rows))
    slots = problem.slots
    task_rows = problem.task_rows
    task_candidates = problem.task_candidates
    existing_teacher_slot = problem.existing_teacher_slot
    existing_class_slot = problem.existing_class_slot
    existing_teacher_day = problem.existing_teacher_day
    ppd = problem.periods_per_day
    assignments = problem.assignments
    p = problem.project
    existing = problem.existing
    assignment_by_id = problem.assignment_by_id

    def cp_time_left():
        return max(0.0, min(deadline, phase_deadline or deadline) - time.monotonic())

    if cp_time_left() <= 0.05:
        return None
    try:
        from ortools.sat.python import cp_model
    except (ImportError, OSError) as exc:
        logger.warning("CP-SAT unavailable (%s); using the fallback scheduler", type(exc).__name__)
        return None

    if neighborhood is None and compact_task_groups(problem) is not None:
        return solve_compact_cp_sat(
            problem, budget, allow_partial=allow_partial, incumbent=incumbent,
            phase_deadline=phase_deadline, search_phases=search_phases, random_seed=random_seed,
        )

    model = cp_model.CpModel()
    slot_var_by_teacher = defaultdict(list)
    slot_var_by_class = defaultdict(list)
    day_var_by_teacher = defaultdict(list)
    task_options = []
    optional_unscheduled_by_task = []
    task_start_vars = []
    unscheduled_sentinel = max(slots, default=-1) + 1
    incumbent_genes = genes_from_candidate(incumbent) if incumbent is not None else None

    for index, (task, candidates) in enumerate(zip(task_rows, task_candidates)):
        if cp_time_left() <= 0.05:
            return None
        frozen = neighborhood is not None and index not in neighborhood
        if frozen:
            candidates = tuple(row for row in candidates if row[0] == incumbent_genes[index])
        (
            assignment,
            group_index,
            size,
            explicit,
            forced,
            anchor_slots,
            planned_starts,
        ) = task
        missing_size = size - len(anchor_slots)
        rows = []
        for slot, group_slots, new_slots, day, session, period in candidates:
            var = model.NewBoolVar(f"task_{index}_start_{slot}")
            row = (slot, new_slots, group_slots, day, session, period, var)
            rows.append(row)
            for candidate in new_slots:
                slot_var_by_teacher[(assignment.teacher_id, candidate)].append(var)
                slot_var_by_class[(assignment.class_id, candidate)].append(var)
            day_var_by_teacher[(assignment.teacher_id, day)].append(
                (var, missing_size)
            )

        option_sum = sum(row[6] for row in rows)
        # Pins remain mandatory. Only whole movable tasks may be omitted,
        # so a required double block can never be split by the partial solve.
        if not rows and (not allow_partial or forced is not None):
            if neighborhood is not None:
                return None
            missing = sum(task[2] - len(task[5]) for task in task_rows)
            return {
                "lessons": [],
                "unscheduled": missing,
                "score": missing * 10000,
                "solver": "cp_sat_feasibility",
                "proven_infeasible": True,
                "maximum_placed": False,
            }
        unscheduled = (
            model.NewBoolVar(f"task_{index}_unscheduled")
            if allow_partial and forced is None else None
        )
        model.Add(option_sum + (unscheduled if unscheduled is not None else 0) == 1)
        if frozen and unscheduled is not None:
            model.Add(unscheduled == int(incumbent_genes[index] is None))
        start_expr = sum(row[0] * row[6] for row in rows)
        if unscheduled is not None:
            start_expr += unscheduled_sentinel * unscheduled

        start_var = model.NewIntVar(
            0, unscheduled_sentinel, f"task_{index}_start_value"
        )
        model.Add(start_var == start_expr)
        task_start_vars.append(start_var)
        task_options.append(rows)
        optional_unscheduled_by_task.append(unscheduled)

    # Teacher/class collisions for every concrete timetable slot.
    for (teacher_id, slot), vars_for_slot in slot_var_by_teacher.items():
        model.Add(
            sum(vars_for_slot) + existing_teacher_slot[(teacher_id, slot)] <= 1
        )
    for (class_id, slot), vars_for_slot in slot_var_by_class.items():
        model.Add(sum(vars_for_slot) + existing_class_slot[(class_id, slot)] <= 1)

    # Teacher daily workload.
    for (teacher_id, day), weighted in day_var_by_teacher.items():
        model.Add(
            sum(var * weight for var, weight in weighted)
            + existing_teacher_day[(teacher_id, day)]
            <= ppd
        )

    # Both CP formulations use the same class/subject session rules.
    occupancy_by_class_subject_slot = defaultdict(list)
    for index, rows in enumerate(task_options):
        assignment = task_rows[index][0]
        for _start, new_slots, _group_slots, _day, _session, _period, var in rows:
            for candidate in new_slots:
                occupancy_by_class_subject_slot[
                    (assignment.class_id, assignment.subject_id, candidate)
                ].append(var)
    add_subject_session_constraints(model, problem, occupancy_by_class_subject_slot)

    # Break permutation symmetry among otherwise-identical tasks belonging
    # to the same assignment.  Unscheduled tasks use a sentinel, so <= also
    # ensures any omitted copies are pushed to the end of the group.
    symmetry_groups = defaultdict(list)
    for index, (task, candidates) in enumerate(zip(task_rows, task_candidates)):
        # Local repairs freeze individual task identities. Permuting equal
        # tasks across that boundary would change the frozen placements.
        if neighborhood is not None:
            break
        assignment, group_index, size, explicit, forced, anchor_slots, _ = task
        if forced is not None or anchor_slots:
            continue
        signature = (
            assignment.id,
            size,
            tuple(row[0] for row in candidates),
        )
        symmetry_groups[signature].append((group_index, index))
    for group in symmetry_groups.values():
        group.sort()
        for (_left_group, left), (_right_group, right) in zip(group, group[1:]):
            model.Add(task_start_vars[left] <= task_start_vars[right])

    if incumbent is not None:
        hint_starts = genes_from_candidate(incumbent)
        for group in symmetry_groups.values():
            indices = [index for _group_index, index in sorted(group)]
            starts = sorted((hint_starts[index] for index in indices),
                            key=lambda start: unscheduled_sentinel if start is None else start)
            for index, start in zip(indices, starts):
                hint_starts[index] = start
        for index, rows in enumerate(task_options):
            for start, *_rest, var in rows:
                model.AddHint(var, int(start == hint_starts[index]))
            omitted = optional_unscheduled_by_task[index]
            if omitted is not None:
                model.AddHint(omitted, int(hint_starts[index] is None))

    total_budget = cp_time_left()

    def make_solver(time_limit: float):
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(0.05, time_limit)
        solver.parameters.num_search_workers = max(1, min(8, os.cpu_count() or 1))
        solver.parameters.random_seed = random_seed
        return solver

    def solve_model(solver, phase):
        started = time.monotonic()
        status = solver.Solve(model)
        search_phases.append({
            "phase": phase,
            "status": solver.StatusName(status),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "movable_tasks": len(neighborhood) if neighborhood is not None else len(task_rows),
            "random_seed": random_seed,
        })
        return status

    def extract_result(solver, status, solver_name: str):
        lessons = []
        final_slots = defaultdict(set)
        for lesson in existing:
            final_slots[lesson.assignment_id].add(lesson.slot)
        unscheduled_count = 0
        chosen_starts = [None] * len(task_rows)
        for index, rows in enumerate(task_options):
            assignment = task_rows[index][0]
            forced = task_rows[index][4]
            unscheduled_var = optional_unscheduled_by_task[index]
            if unscheduled_var is not None and solver.Value(unscheduled_var):
                unscheduled_count += max(
                    1, task_rows[index][2] - len(task_rows[index][5])
                )
                continue
            for (
                start,
                new_slots,
                _group_slots,
                _day,
                _session,
                _period,
                var,
            ) in rows:
                if solver.Value(var):
                    chosen_starts[index] = start
                    for candidate in new_slots:
                        lessons.append(
                            (
                                assignment.id,
                                candidate,
                                forced is not None,
                                f"task:{index}",
                            )
                        )
                        final_slots[assignment.id].add(candidate)
                    break

        soft_score = unscheduled_count * 10000.0 + _schedule_soft_score(
            p, assignments, assignment_by_id, final_slots
        )
        return {
            "lessons": lessons,
            "unscheduled": unscheduled_count,
            "score": round(soft_score, 2),
            "genes": chosen_starts,
            "solver": solver_name,
            "optimal": status == cp_model.OPTIMAL,
            "wall_time": round(solver.WallTime(), 3),
        }

    if total_budget <= 0.05:
        return None

    if allow_partial:
        omitted_periods = sum(
            var * (task_rows[index][2] - len(task_rows[index][5]))
            for index, var in enumerate(optional_unscheduled_by_task)
            if var is not None
        )
        if neighborhood is not None:
            model.Add(omitted_periods < incumbent["unscheduled"])
        elif incumbent is not None and all(
            task[4] is None or incumbent_genes[index] is not None
            for index, task in enumerate(task_rows)
        ):
            model.Add(omitted_periods <= incumbent["unscheduled"])
        model.Minimize(omitted_periods)

    phase = "cp_sat_feasibility"
    if allow_partial:
        phase = "cp_sat_neighborhood" if neighborhood is not None else "cp_sat_partial"
    solver = make_solver(cp_time_left())
    status = solve_model(solver, phase)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # A failed neighborhood only rules out that local repair.
        if status == cp_model.INFEASIBLE and neighborhood is None:
            missing = sum(task[2] - len(task[5]) for task in task_rows)
            return {"lessons": [], "unscheduled": missing, "score": missing * 10000,
                    "solver": phase, "proven_infeasible": True, "maximum_placed": False}
        return None

    result = extract_result(solver, status, phase)
    result["maximum_placed"] = result["unscheduled"] == 0 or (
        allow_partial and neighborhood is None and status == cp_model.OPTIMAL
    )
    result["proven_infeasible"] = result["maximum_placed"] and result["unscheduled"] > 0
    result["optimal"] = False
    result["search_limited"] = not result["maximum_placed"]
    return result
