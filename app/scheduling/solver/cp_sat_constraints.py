"""Hard class/subject session rules shared by both CP-SAT models."""
from app.scheduling.rules import assignment_consecutive_limit


def add_subject_session_constraints(model, problem, slot_variables):
    p = problem.project
    limits = {}
    capped_pairs = set()
    for assignment in problem.assignments:
        key = assignment.class_id, assignment.subject_id
        limit = assignment_consecutive_limit(p, assignment)
        limits[key] = min(limits.get(key, limit), limit)
        if assignment.block_mode == "max_two_consecutive":
            capped_pairs.add(key)
    for (class_id, subject_id), limit in limits.items():
        for day in range(p.days):
            for session in range(p.sessions):
                base = day * problem.periods_per_day + session * p.periods_per_session
                occupancy = [
                    sum(slot_variables[class_id, subject_id, base + period])
                    + problem.existing_css[class_id, subject_id, base + period]
                    for period in range(p.periods_per_session)
                ]
                if (class_id, subject_id) in capped_pairs:
                    model.Add(sum(occupancy) <= 2)
                    # Selecting any nonadjacent pair is forbidden, including
                    # separated singles and a second pair in the same session.
                    for left in range(p.periods_per_session):
                        for right in range(left + 2, p.periods_per_session):
                            model.Add(occupancy[left] + occupancy[right] <= 1)
                else:
                    for start in range(p.periods_per_session - limit):
                        model.Add(sum(occupancy[start:start + limit + 1]) <= limit)
