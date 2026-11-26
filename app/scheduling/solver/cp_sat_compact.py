"""Solve interchangeable single periods without assigning each a separate identity."""
from __future__ import annotations

from collections import defaultdict
import os
import time

from .context import genes_from_candidate
from .cp_sat_constraints import add_subject_session_constraints
from .scoring import _schedule_soft_score


def compact_task_groups(problem):
    """Pins, anchored patterns and atomic double blocks use the task model."""
    groups = defaultdict(list)
    domains = {}
    for index, (task, candidates) in enumerate(zip(problem.task_rows, problem.task_candidates)):
        assignment, _, size, explicit, forced, anchors, _ = task
        if size != 1 or explicit or forced is not None or anchors:
            return None
        starts = tuple(row[0] for row in candidates)
        if assignment.id in domains and domains[assignment.id] != starts:
            return None
        domains[assignment.id] = starts
        groups[assignment.id].append(index)
    return groups, domains


def compact_capacity_shortfall(problem, groups, domains):
    """Bound omissions by matching each resource's demand to its available slots."""
    from ortools.graph.python import max_flow

    deficits = []
    for field in ("teacher_id", "class_id"):
        resource_groups = defaultdict(list)
        for assignment_id, indices in groups.items():
            owner = getattr(problem.assignment_by_id[assignment_id], field)
            resource_groups[owner].append((assignment_id, len(indices)))
        deficit = 0
        for rows in resource_groups.values():
            slots = sorted({slot for assignment_id, _count in rows for slot in domains[assignment_id]})
            if not slots:
                deficit += sum(count for _assignment_id, count in rows)
                continue
            slot_nodes = {slot: len(rows) + index + 1 for index, slot in enumerate(slots)}
            sink = len(rows) + len(slots) + 1
            flow = max_flow.SimpleMaxFlow()
            for node, (assignment_id, count) in enumerate(rows, 1):
                flow.add_arc_with_capacity(0, node, count)
                for slot in domains[assignment_id]:
                    flow.add_arc_with_capacity(node, slot_nodes[slot], 1)
            for node in slot_nodes.values():
                flow.add_arc_with_capacity(node, sink, 1)
            if flow.solve(0, sink) == flow.OPTIMAL:
                deficit += sum(count for _assignment_id, count in rows) - flow.optimal_flow()
        deficits.append(deficit)
    # Teacher and class shortages may concern the same omitted periods.
    return max(deficits, default=0)


def solve_compact_cp_sat(problem, budget, *, allow_partial=False, incumbent=None,
                         phase_deadline=None, search_phases=None, random_seed=42):
    """Return ordinary task genes so repair and GA can reuse compact results."""
    grouped = compact_task_groups(problem)
    if grouped is None:
        return None
    from ortools.sat.python import cp_model

    groups, domains = grouped
    shortfall = compact_capacity_shortfall(problem, groups, domains)
    if shortfall and not allow_partial:
        missing = len(problem.task_rows)
        if search_phases is not None:
            search_phases.append({"phase": "capacity_bound", "status": "INFEASIBLE",
                                  "minimum_unscheduled": shortfall})
        return {"lessons": [], "unscheduled": missing, "score": missing * 10000,
                "solver": "capacity_bound", "proven_infeasible": True, "optimal": False}
    deadline = min(budget.deadline, phase_deadline or budget.deadline)

    def time_left():
        return max(0.0, deadline - time.monotonic())

    if time_left() <= 0.05:
        return None
    model = cp_model.CpModel()
    variables = {}
    teacher_slot = defaultdict(list)
    class_slot = defaultdict(list)
    subject_slot = defaultdict(list)
    omitted = []
    p = problem.project
    hints = genes_from_candidate(incumbent or {}, len(problem.task_rows))

    for assignment_id, indices in groups.items():
        assignment = problem.assignment_by_id[assignment_id]
        selected_hint = {hints[index] for index in indices if hints[index] is not None}
        rows = []
        for slot in domains[assignment_id]:
            var = model.NewBoolVar(f"assignment_{assignment_id}_slot_{slot}")
            variables[assignment_id, slot] = var
            rows.append(var)
            teacher_slot[assignment.teacher_id, slot].append(var)
            class_slot[assignment.class_id, slot].append(var)
            subject_slot[assignment.class_id, assignment.subject_id, slot].append(var)
            if incumbent is not None:
                model.AddHint(var, int(slot in selected_hint))
        count = len(indices)
        if allow_partial:
            missing = model.NewIntVar(0, count, f"assignment_{assignment_id}_missing")
            model.Add(sum(rows) + missing == count)
            omitted.append(missing)
            if incumbent is not None:
                model.AddHint(missing, count - len(selected_hint))
        else:
            model.Add(sum(rows) == count)
        if time_left() <= 0.05:
            return None

    for key, rows in teacher_slot.items():
        model.Add(sum(rows) + problem.existing_teacher_slot[key] <= 1)
    for key, rows in class_slot.items():
        model.Add(sum(rows) + problem.existing_class_slot[key] <= 1)
    add_subject_session_constraints(model, problem, subject_slot)

    def run(phase, seconds):
        if time_left() <= 0.05:
            return None, cp_model.UNKNOWN
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(0.01, min(seconds, time_left()))
        solver.parameters.num_search_workers = max(1, min(8, os.cpu_count() or 1))
        solver.parameters.random_seed = random_seed
        started = time.monotonic()
        status = solver.Solve(model)
        if search_phases is not None:
            search_phases.append({
                "phase": phase, "status": solver.StatusName(status),
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "movable_tasks": len(problem.task_rows),
                "placement_variables": len(variables),
                "random_seed": random_seed,
            })
        return solver, status

    def extract(solver, phase):
        genes = [None] * len(problem.task_rows)
        lessons = []
        final_slots = defaultdict(set)
        for lesson in problem.existing:
            final_slots[lesson.assignment_id].add(lesson.slot)
        for assignment_id, indices in groups.items():
            chosen = [slot for slot in domains[assignment_id]
                      if solver.Value(variables[assignment_id, slot])]
            ordered_indices = sorted(indices, key=lambda i: problem.task_rows[i][1])
            for index, slot in zip(ordered_indices, sorted(chosen)):
                genes[index] = slot
                lessons.append((assignment_id, slot, False, f"task:{index}"))
                final_slots[assignment_id].add(slot)
        missing = len(genes) - len(lessons)
        return {
            "lessons": lessons, "genes": genes, "unscheduled": missing,
            "score": round(missing * 10000 + _schedule_soft_score(
                p, problem.assignments, problem.assignment_by_id, final_slots), 2),
            "solver": phase, "optimal": False,
            "maximum_placed": missing == 0, "search_limited": missing > 0,
            "wall_time": round(solver.WallTime(), 3),
        }

    if allow_partial:
        model.Add(sum(omitted) >= shortfall)
        if incumbent is not None:
            model.Add(sum(omitted) <= incumbent["unscheduled"])
        model.Minimize(sum(omitted))
    phase = "cp_sat_compact_partial" if allow_partial else "cp_sat_compact_feasibility"
    solver, status = run(phase, time_left())
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if status == cp_model.INFEASIBLE:
            missing = len(problem.task_rows)
            return {"lessons": [], "unscheduled": missing, "score": missing * 10000,
                    "solver": phase, "proven_infeasible": True, "optimal": False}
        return None
    result = extract(solver, phase)
    if allow_partial:
        result["maximum_placed"] = status == cp_model.OPTIMAL or result["unscheduled"] == 0
        result["proven_infeasible"] = result["maximum_placed"] and result["unscheduled"] > 0
    result["search_limited"] = not result["maximum_placed"]
    return result
