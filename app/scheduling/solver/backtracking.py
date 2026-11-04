"""Bounded exact search for small residual scheduling problems."""
from __future__ import annotations

from collections import Counter, defaultdict

from .context import SearchBudget
from .problem import SchedulingProblem
from .scoring import _schedule_soft_score
from app.scheduling.rules import assignment_prefers_double


def exact_search(problem: SchedulingProblem, budget: SearchBudget, node_limit: int):
    """Return (complete candidate, exhausted, nodes), respecting the shared deadline."""
    deadline_hit = budget.expired
    existing = problem.existing
    assignment_by_id = problem.assignment_by_id
    ppd = problem.periods_per_day
    task_rows = problem.task_rows
    p = problem.project
    assignments = problem.assignments
    task_candidates = problem.task_candidates

    teacher_busy = defaultdict(set)
    class_busy = defaultdict(set)
    assignment_busy = defaultdict(set)
    teacher_day = Counter()
    class_sub_day = Counter()
    class_sub_slots = defaultdict(set)
    for lesson in existing:
        assignment = assignment_by_id.get(lesson.assignment_id)
        if not assignment:
            continue
        day = lesson.slot // ppd
        teacher_busy[assignment.teacher_id].add(lesson.slot)
        class_busy[assignment.class_id].add(lesson.slot)
        assignment_busy[assignment.id].add(lesson.slot)
        teacher_day[(assignment.teacher_id, day)] += 1
        class_sub_day[(assignment.class_id, assignment.subject_id, day)] += 1
        class_sub_slots[(assignment.class_id, assignment.subject_id, day)].add(
            lesson.slot % ppd
        )

    placed_by_task = {}
    remaining = set(range(len(task_rows)))
    nodes = 0
    limit_hit = False

    def options_for(index: int):
        (
            assignment,
            group_index,
            size,
            explicit,
            forced,
            anchor_slots,
            planned_starts,
        ) = task_rows[index]
        missing_size = size - len(anchor_slots)
        options = []
        for slot, group_slots, new_slots, day, session, period in task_candidates[
            index
        ]:
            if any(
                candidate in teacher_busy[assignment.teacher_id]
                or candidate in class_busy[assignment.class_id]
                for candidate in new_slots
            ):
                continue
            if (
                teacher_day[(assignment.teacher_id, day)] + missing_size
                > ppd
            ):
                continue
            existing_periods = [
                candidate % p.periods_per_session
                for candidate in class_sub_slots[
                    (assignment.class_id, assignment.subject_id, day)
                ]
                if candidate // p.periods_per_session == session
            ]
            run = sorted(set(existing_periods) | set(range(period, period + size)))
            longest = current = 1
            for left, right in zip(run, run[1:]):
                current = current + 1 if right == left + 1 else 1
                longest = max(longest, current)
            if longest > max(
                1, int(p.periods_per_session)
            ):
                continue
            adjacent_same = 0
            if assignment_prefers_double(assignment):
                if period > 0 and slot - 1 in assignment_busy[assignment.id]:
                    adjacent_same += 1
                if (
                    period + size < p.periods_per_session
                    and slot + size in assignment_busy[assignment.id]
                ):
                    adjacent_same += 1
            score = (
                class_sub_day[(assignment.class_id, assignment.subject_id, day)] * 8
                + sum(
                    (candidate % p.periods_per_session) * 0.15
                    for candidate in new_slots
                )
                - adjacent_same * 7
            )
            options.append((score, slot, group_slots, new_slots, day))
        options.sort(key=lambda item: (item[0], item[1]))
        return options

    def apply(index: int, option):
        _score, slot, group_slots, new_slots, day = option
        assignment = task_rows[index][0]
        forced = task_rows[index][4]
        for candidate in new_slots:
            teacher_busy[assignment.teacher_id].add(candidate)
            class_busy[assignment.class_id].add(candidate)
            assignment_busy[assignment.id].add(candidate)
            class_sub_slots[(assignment.class_id, assignment.subject_id, day)].add(
                candidate % ppd
            )
        teacher_day[(assignment.teacher_id, day)] += len(new_slots)
        class_sub_day[(assignment.class_id, assignment.subject_id, day)] += len(
            new_slots
        )
        placed_by_task[index] = (
            assignment.id,
            tuple(new_slots),
            forced is not None,
        )

    def undo(index: int, option):
        _score, slot, group_slots, new_slots, day = option
        assignment = task_rows[index][0]
        placed_by_task.pop(index, None)
        teacher_day[(assignment.teacher_id, day)] -= len(new_slots)
        class_sub_day[(assignment.class_id, assignment.subject_id, day)] -= len(
            new_slots
        )
        for candidate in new_slots:
            teacher_busy[assignment.teacher_id].remove(candidate)
            class_busy[assignment.class_id].remove(candidate)
            assignment_busy[assignment.id].remove(candidate)
            class_sub_slots[
                (assignment.class_id, assignment.subject_id, day)
            ].remove(candidate % ppd)

    def search():
        nonlocal nodes, limit_hit
        if not remaining:
            return True
        nodes += 1
        if nodes > node_limit or deadline_hit(0.02):
            limit_hit = True
            return False
        selected_index = None
        selected_options = None
        # Dynamic MRV on top of the static MRV ordering.
        for index in tuple(remaining):
            options = options_for(index)
            if not options:
                return False
            if selected_options is None or len(options) < len(selected_options):
                selected_index = index
                selected_options = options
                if len(options) == 1:
                    break
        remaining.remove(selected_index)
        for option in selected_options:
            apply(selected_index, option)
            if search():
                return True
            undo(selected_index, option)
            if limit_hit:
                break
        remaining.add(selected_index)
        return False

    solved = search()
    if not solved:
        return None, not limit_hit, nodes
    lessons = []
    for index in range(len(task_rows)):
        assignment_id, new_slots, locked = placed_by_task[index]
        lessons.extend(
            (assignment_id, slot, locked, f"task:{index}") for slot in new_slots
        )
    final_slots = defaultdict(set)
    for lesson in existing:
        final_slots[lesson.assignment_id].add(lesson.slot)
    for assignment_id, slot, _locked, _block_token in lessons:
        final_slots[assignment_id].add(slot)
    soft_score = _schedule_soft_score(p, assignments, assignment_by_id, final_slots)
    return (
        {
            "lessons": lessons,
            "unscheduled": 0,
            "score": round(soft_score, 2),
            "exact": True,
            "solver": "exact_backtracking",
        },
        True,
        nodes,
    )
