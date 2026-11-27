"""Model the canonical soft score after the number of omitted periods is fixed."""
from collections import defaultdict

from app.scheduling.rules import assignment_prefers_double

from .scoring import (
    PREFERRED_DOUBLE_PENALTY, SAME_DAY_PENALTY, TEACHER_GAP_PENALTY, _schedule_soft_score, soft_score,
)


def quality_neighborhood(problem, incumbent, limit, budget):
    """Choose a small set of movable tasks from the teachers with the highest penalties."""
    tasks_by_teacher = defaultdict(list)
    for index, (task, candidates) in enumerate(zip(problem.task_rows, problem.task_candidates)):
        if task[4] is None and len(candidates) > 1:
            tasks_by_teacher[task[0].teacher_id].append(index)

    assignments_by_teacher = defaultdict(list)
    for assignment in problem.assignments:
        assignments_by_teacher[assignment.teacher_id].append(assignment)
    slots = defaultdict(set)
    for lesson in problem.existing:
        slots[lesson.assignment_id].add(lesson.slot)
    for assignment_id, slot, *_ in incumbent["lessons"]:
        slots[assignment_id].add(slot)

    penalties = []
    for teacher in tasks_by_teacher:
        if budget.expired():
            return None
        penalty = _schedule_soft_score(
            problem.project, assignments_by_teacher[teacher], problem.assignment_by_id, slots
        )
        if penalty:
            penalties.append((-penalty, teacher))

    active = set()
    for _, teacher in sorted(penalties):
        active.update(tasks_by_teacher[teacher][:limit - len(active)])
        if len(active) >= limit:
            break
    return active


def add_quality_objective(model, problem, assignment_options, teacher_options, incumbent, budget):
    """Return False if the time budget expires while building the objective."""
    p = problem.project
    pps = p.periods_per_session
    ppd = problem.periods_per_day
    penalties = []

    def occupancy(options, retained):
        if retained:
            return 1
        if not options:
            return 0
        if len(options) == 1:
            return options[0]
        # At most one option can occupy a slot under the collision constraints.
        active = model.NewBoolVar("")
        model.Add(active == sum(options))
        return active

    def negate(literal):
        return 1 - literal if isinstance(literal, int) else literal.Not()

    def all_true(*literals):
        if any(isinstance(item, int) and item == 0 for item in literals):
            return 0
        variables = [item for item in literals if not isinstance(item, int)]
        if not variables:
            return 1
        if len(variables) == 1:
            return variables[0]
        active = model.NewBoolVar("")
        model.AddBoolAnd(variables).OnlyEnforceIf(active)
        model.AddBoolOr([item.Not() for item in variables]).OnlyEnforceIf(active.Not())
        return active

    def any_true(literals):
        return negate(all_true(*(negate(literal) for literal in literals)))

    for assignment in problem.assignments:
        if budget.expired():
            return False
        aid = assignment.id
        retained = problem.existing_assignment_slots.get(aid, set())
        occupied = [
            occupancy(assignment_options.get((aid, slot), ()), slot in retained)
            for slot in problem.slots
        ]
        for day in range(p.days):
            day_slots = occupied[day * ppd:(day + 1) * ppd]
            penalties.append(SAME_DAY_PENALTY * (sum(day_slots) - any_true(day_slots)))
        if assignment_prefers_double(assignment):
            target_pairs = int(assignment.periods_per_week or 0) // 2
            pairs = []
            for start in range(0, len(occupied), pps):
                # A run counts only if it has exactly two periods in this session.
                session = [0, *occupied[start:start + pps], 0]
                for i in range(1, pps):
                    pairs.append(all_true(negate(session[i - 1]), session[i], session[i + 1],
                                          negate(session[i + 2])))
            penalties.append(PREFERRED_DOUBLE_PENALTY * (target_pairs - sum(pairs)))

    for teacher_id in problem.teachers:
        if budget.expired():
            return False
        occupied = [
            occupancy(teacher_options.get((teacher_id, slot), ()),
                      problem.existing_teacher_slot.get((teacher_id, slot), 0))
            for slot in problem.slots
        ]
        for start in range(0, len(occupied), pps):
            session = occupied[start:start + pps]
            for i in range(1, pps - 1):
                gap = all_true(any_true(session[:i]), negate(session[i]), any_true(session[i + 1:]))
                penalties.append(TEACHER_GAP_PENALTY * gap)

    objective = sum(penalties)
    model.Add(objective <= soft_score(incumbent))
    model.Minimize(objective)
    return True
