from __future__ import annotations

from collections import defaultdict, deque

from app.scheduling.rules import assignment_requires_double, required_double_block_state


def saved_placement_genes(project, tasks, candidates, saved_lessons, retained_lessons):
    """Map saved movable lessons to solver tasks without inferring double blocks."""
    available = defaultdict(set)
    saved_by_assignment = defaultdict(list)
    for lesson in saved_lessons:
        available[lesson.assignment_id].add(lesson.slot)
        saved_by_assignment[lesson.assignment_id].append(lesson)
    for lesson in retained_lessons:
        available[lesson.assignment_id].discard(lesson.slot)

    explicit_blocks = {}
    for task in tasks:
        owner = task[0]
        if assignment_requires_double(owner) and owner.id not in explicit_blocks:
            state = required_double_block_state(project, owner, saved_by_assignment[owner.id])
            explicit_blocks[owner.id] = (
                {(group["start"], group["size"]) for group in state["groups"]}
                if state["valid"] else set()
            )

    genes = [None] * len(tasks)
    for index, (task, options) in enumerate(zip(tasks, candidates)):
        owner, _group, size, explicit, _forced, _anchors, _starts = task
        for row in options:
            start, _group_slots, new_slots, *_ = row
            if not set(new_slots).issubset(available[owner.id]):
                continue
            if explicit and (start, size) not in explicit_blocks[owner.id]:
                continue
            genes[index] = start
            available[owner.id].difference_update(new_slots)
            break
    return genes


def conflict_neighborhood(tasks, candidates, genes, limit):
    """Expand from omitted tasks through teacher/class conflicts in the incumbent.

    Tasks outside the returned set will stay at their incumbent positions during
    a local solve. Every omitted task is included, even when there are more than
    the requested limit. Pins remain enforced by the shared CP-SAT model.
    """
    teacher_busy = {}
    class_busy = {}
    for index, (task, options, start) in enumerate(zip(tasks, candidates, genes)):
        if start is None:
            continue
        row = next(row for row in options if row[0] == start)
        for slot in row[2]:
            teacher_busy[(task[0].teacher_id, slot)] = index
            class_busy[(task[0].class_id, slot)] = index

    active = {index for index, start in enumerate(genes) if start is None}
    queue = deque(sorted(active, key=lambda index: (len(candidates[index]), index)))
    while queue and len(active) < limit:
        index = queue.popleft()
        owner = tasks[index][0]
        blockers = set()
        for row in candidates[index]:
            for slot in row[2]:
                blockers.update((teacher_busy.get((owner.teacher_id, slot)),
                                 class_busy.get((owner.class_id, slot))))
        blockers.discard(None)
        for blocker in sorted(blockers - active, key=lambda i: (len(candidates[i]), i)):
            if tasks[blocker][4] is not None:
                continue
            active.add(blocker)
            queue.append(blocker)
            if len(active) >= limit:
                break
    return frozenset(active)
