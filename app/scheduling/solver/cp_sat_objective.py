"""Canonical preference objective shared by CP-SAT formulations."""
from app.scheduling.rules import assignment_prefers_double


def add_soft_objective(
    model, problem, assignment_slot_vars,
    slot_var_by_teacher, day_var_by_class_subject,
):
    """Build preference variables only after a valid placement exists."""
    p = problem.project
    ppd = problem.periods_per_day
    assignments = problem.assignments
    teachers = problem.teachers
    existing_assignment_slots = problem.existing_assignment_slots
    existing_class_subject_day = problem.existing_class_subject_day
    existing_teacher_slot = problem.existing_teacher_slot
    objective_terms = []
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
    return objective_terms
