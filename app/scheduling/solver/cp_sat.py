"""CP-SAT feasibility, partial placement and local repair models."""
from __future__ import annotations

from collections import defaultdict
from functools import partial
import logging
import os
import time

from .context import SearchBudget, genes_from_candidate as _candidate_genes
from .problem import SchedulingProblem
from .scoring import _schedule_soft_score
from app.scheduling.rules import assignment_prefers_double

logger = logging.getLogger("smart_tkb")


def solve_cp_sat(
    problem: SchedulingProblem, budget: SearchBudget, allow_partial: bool = False,
    incumbent=None, *, neighborhood=None, phase_deadline=None, search_phases=None,
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
    subjects = problem.subjects
    p = problem.project
    existing_css = problem.existing_css
    existing = problem.existing
    existing_class_subject_day = problem.existing_class_subject_day
    teachers = problem.teachers
    existing_assignment_slots = problem.existing_assignment_slots
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

    model = cp_model.CpModel()
    slot_var_by_teacher = defaultdict(list)
    slot_var_by_class = defaultdict(list)
    day_var_by_teacher = defaultdict(list)
    day_var_by_class_subject = defaultdict(list)
    assignment_slot_vars = defaultdict(list)
    objective_terms = []
    task_options = []
    optional_unscheduled_by_task = []
    task_start_vars = []
    all_option_vars = []
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
            all_option_vars.append(var)
            for candidate in new_slots:
                slot_var_by_teacher[(assignment.teacher_id, candidate)].append(var)
                slot_var_by_class[(assignment.class_id, candidate)].append(var)
                assignment_slot_vars[(assignment.id, candidate)].append(var)
            day_var_by_teacher[(assignment.teacher_id, day)].append(
                (var, missing_size)
            )
            day_var_by_class_subject[
                (assignment.class_id, assignment.subject_id, day)
            ].append((var, missing_size))

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

    # Subject max-consecutive constraint.  Iterate each class/subject pair
    # once instead of duplicating identical window constraints per assignment.
    occupancy_by_class_subject_slot = defaultdict(list)
    for index, rows in enumerate(task_options):
        assignment = task_rows[index][0]
        for _start, new_slots, _group_slots, _day, _session, _period, var in rows:
            for candidate in new_slots:
                occupancy_by_class_subject_slot[
                    (assignment.class_id, assignment.subject_id, candidate)
                ].append(var)
    class_subject_pairs = {
        (assignment.class_id, assignment.subject_id)
        for assignment in assignments
        if assignment.subject_id in subjects
    }
    for class_id, subject_id in class_subject_pairs:
        subject = subjects[subject_id]
        max_run = max(1, int(p.periods_per_session))
        window = max_run + 1
        if window > p.periods_per_session:
            continue
        for day in range(p.days):
            for session in range(p.sessions):
                base = day * ppd + session * p.periods_per_session
                for start_period in range(p.periods_per_session - window + 1):
                    window_slots = [
                        base + start_period + offset for offset in range(window)
                    ]
                    expr = []
                    fixed_count = 0
                    for candidate in window_slots:
                        expr.extend(
                            occupancy_by_class_subject_slot[
                                (class_id, subject_id, candidate)
                            ]
                        )
                        fixed_count += existing_css[
                            (class_id, subject_id, candidate)
                        ]
                    if expr or fixed_count:
                        model.Add(sum(expr) + fixed_count <= max_run)

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

    def add_soft_objective():
        """Build preference variables only after a valid placement exists."""
        # Soft objective for preferred_double.  Reward only an isolated run of
        # exactly two periods, matching the UI's definition.
        for assignment in assignments:
            if not assignment_prefers_double(assignment):
                continue
            for day in range(p.days):
                for session in range(p.sessions):
                    base = day * ppd + session * p.periods_per_session
                    for period in range(p.periods_per_session - 1):
                        left = base + period
                        right = left + 1
                        left_vars = assignment_slot_vars[(assignment.id, left)]
                        right_vars = assignment_slot_vars[(assignment.id, right)]
                        left_fixed = (
                            1 if left in existing_assignment_slots[assignment.id] else 0
                        )
                        right_fixed = (
                            1
                            if right in existing_assignment_slots[assignment.id]
                            else 0
                        )
                        if not (left_fixed or left_vars) or not (
                            right_fixed or right_vars
                        ):
                            continue

                        previous = left - 1 if period > 0 else None
                        following = (
                            right + 1 if period + 2 < p.periods_per_session else None
                        )
                        previous_vars = (
                            assignment_slot_vars[(assignment.id, previous)]
                            if previous is not None
                            else []
                        )
                        following_vars = (
                            assignment_slot_vars[(assignment.id, following)]
                            if following is not None
                            else []
                        )
                        previous_fixed = (
                            1
                            if previous is not None
                            and previous in existing_assignment_slots[assignment.id]
                            else 0
                        )
                        following_fixed = (
                            1
                            if following is not None
                            and following in existing_assignment_slots[assignment.id]
                            else 0
                        )

                        pair = model.NewBoolVar(
                            f"preferred_pair_{assignment.id}_{left}_{right}"
                        )
                        left_occupancy = sum(left_vars) + left_fixed
                        right_occupancy = sum(right_vars) + right_fixed
                        previous_occupancy = sum(previous_vars) + previous_fixed
                        following_occupancy = sum(following_vars) + following_fixed
                        model.Add(pair <= left_occupancy)
                        model.Add(pair <= right_occupancy)
                        model.Add(pair <= 1 - previous_occupancy)
                        model.Add(pair <= 1 - following_occupancy)
                        objective_terms.append(-14 * pair)

        # Spread the same class/subject across days.
        for (class_id, subject_id, day), weighted in day_var_by_class_subject.items():
            existing_count = existing_class_subject_day[(class_id, subject_id, day)]
            total = sum(var * weight for var, weight in weighted) + existing_count
            overflow = model.NewIntVar(
                0,
                p.periods_per_session * p.sessions,
                f"spread_{class_id}_{subject_id}_{day}",
            )
            model.Add(overflow >= total - 1)
            objective_terms.append(8 * overflow)

        # Match the public score exactly: each empty period *inside* a teacher's
        # occupied span in one session costs 2.  The previous adjacency reward
        # was only an approximation and could mark a timetable "optimal" while
        # another timetable had fewer actual idle gaps.
        for teacher_id in teachers:
            for day in range(p.days):
                for session in range(p.sessions):
                    base = day * ppd + session * p.periods_per_session
                    possible = []
                    for period in range(p.periods_per_session):
                        slot = base + period
                        possible.append(
                            bool(
                                existing_teacher_slot[(teacher_id, slot)]
                                or slot_var_by_teacher[(teacher_id, slot)]
                            )
                        )
                    if sum(possible) < 2:
                        continue

                    occupancy = []
                    for period in range(p.periods_per_session):
                        slot = base + period
                        fixed = existing_teacher_slot[(teacher_id, slot)]
                        vars_for_slot = slot_var_by_teacher[(teacher_id, slot)]
                        occ = model.NewBoolVar(
                            f"teacher_occ_{teacher_id}_{day}_{session}_{period}"
                        )
                        model.Add(occ == sum(vars_for_slot) + fixed)
                        occupancy.append(occ)

                    for period in range(1, p.periods_per_session - 1):
                        before = model.NewBoolVar(
                            f"teacher_before_{teacher_id}_{day}_{session}_{period}"
                        )
                        after = model.NewBoolVar(
                            f"teacher_after_{teacher_id}_{day}_{session}_{period}"
                        )
                        model.AddMaxEquality(before, occupancy[:period])
                        model.AddMaxEquality(after, occupancy[period + 1 :])
                        gap = model.NewBoolVar(
                            f"teacher_gap_{teacher_id}_{day}_{session}_{period}"
                        )
                        model.Add(gap <= before)
                        model.Add(gap <= after)
                        model.Add(gap + occupancy[period] <= 1)
                        model.Add(gap >= before + after - occupancy[period] - 1)
                        objective_terms.append(2 * gap)

    total_budget = cp_time_left()

    def make_solver(time_limit: float):
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(0.05, time_limit)
        solver.parameters.num_search_workers = max(1, min(8, os.cpu_count() or 1))
        solver.parameters.random_seed = 42
        return solver

    def solve_model(solver, phase):
        started = time.monotonic()
        status = solver.Solve(model)
        search_phases.append({
            "phase": phase,
            "status": solver.StatusName(status),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "movable_tasks": len(neighborhood) if neighborhood is not None else len(task_rows),
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
        # First maximize placed periods. A feasible partial incumbent must
        # not stop the remaining repair search unless its count is proven.
        omitted_periods = sum(
            var * (task_rows[index][2] - len(task_rows[index][5]))
            for index, var in enumerate(optional_unscheduled_by_task)
            if var is not None
        )
        if neighborhood is not None:
            # Require a real gain. A locally optimal partial timetable is
            # never a proof of the maximum for the whole project.
            model.Add(omitted_periods < incumbent["unscheduled"])
        model.Minimize(omitted_periods)
        solver = make_solver(total_budget * (1.0 if neighborhood is not None else 0.65))
        partial_phase = "cp_sat_neighborhood" if neighborhood is not None else "cp_sat_partial"
        status = solve_model(solver, partial_phase)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            result = extract_result(solver, status, partial_phase)
            result["maximum_placed"] = (
                (neighborhood is None and status == cp_model.OPTIMAL)
                or result["unscheduled"] == 0
            )
            result["optimal"] = False
            result["search_limited"] = not result["maximum_placed"]
            if (
                neighborhood is not None
                or not result["maximum_placed"]
                or cp_time_left() <= 0.10
            ):
                return result

            # Count is now fixed at its best value. Improve preferences
            # without ever exchanging a placed period for a prettier grid.
            model.Add(omitted_periods == result["unscheduled"])
            model.ClearHints()
            for var in all_option_vars:
                model.AddHint(var, solver.Value(var))
            for var in optional_unscheduled_by_task:
                if var is not None:
                    model.AddHint(var, solver.Value(var))
            add_soft_objective()
            if objective_terms and cp_time_left() > 0.10:
                model.Minimize(sum(objective_terms))
                optimize_solver = make_solver(cp_time_left())
                optimize_status = solve_model(optimize_solver, "cp_sat_partial_optimize")
                if optimize_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    optimized = extract_result(
                        optimize_solver, optimize_status, "cp_sat_partial_optimize"
                    )
                    if optimized["score"] <= result["score"]:
                        optimized["maximum_placed"] = True
                        optimized["search_limited"] = optimize_status != cp_model.OPTIMAL
                        return optimized
            return result
        return None

    # Phase 1: pure hard-feasibility search, no soft objective.  Reserve part
    # of the request-wide deadline for GA/backtracking only when CP-SAT fails
    # to find a complete schedule in time.
    hard_time = min(total_budget, max(0.2, total_budget * 0.75))
    solver = make_solver(hard_time)
    status = solve_model(solver, "cp_sat_feasibility")
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if status == cp_model.INFEASIBLE:
            missing = sum(max(1, task[2] - len(task[5])) for task in task_rows)
            return {
                "lessons": [],
                "unscheduled": missing,
                "score": missing * 10000,
                "solver": "cp_sat_feasibility",
                "proven_infeasible": True,
                "wall_time": round(solver.WallTime(), 3),
            }
        logger.info(
            "CP-SAT feasibility phase reached its time limit (status=%s); "
            "using bounded fallback",
            status,
        )
        return None

    hard_result = extract_result(solver, status, "cp_sat_feasibility")
    # A satisfaction solve can report OPTIMAL because there is no objective;
    # that must not be exposed as soft-score optimality.
    hard_result["optimal"] = False

    # Phase 2: reuse the complete timetable as a hint and spend only the
    # remaining global budget improving the canonical soft score.
    if cp_time_left() <= 0.10:
        return hard_result
    model.ClearHints()
    for var in all_option_vars:
        model.AddHint(var, solver.Value(var))
    add_soft_objective()
    if not objective_terms or cp_time_left() <= 0.10:
        return hard_result
    model.Minimize(sum(objective_terms))

    optimize_solver = make_solver(cp_time_left())
    optimize_status = solve_model(optimize_solver, "cp_sat_optimize")
    if optimize_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        optimized = extract_result(
            optimize_solver, optimize_status, "cp_sat_optimize"
        )
        optimized["wall_time"] = round(
            hard_result.get("wall_time", 0) + optimize_solver.WallTime(), 3
        )
        if optimized["score"] <= hard_result["score"]:
            return optimized
        return hard_result

    hard_result["search_limited"] = True
    hard_result["wall_time"] = round(
        hard_result.get("wall_time", 0) + optimize_solver.WallTime(), 3
    )
    return hard_result
