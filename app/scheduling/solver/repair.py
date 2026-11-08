from __future__ import annotations

import time
from collections import Counter, defaultdict

from app.scheduling.rules import assignment_consecutive_limit


def repair_placements(tasks, candidates, genes, existing, assignment_by_id, *, project, deadline, node_limit=12000):
    """Insert missing blocks using bounded chains of movable block relocations.

    Candidate rows already encode availability, session boundaries and anchors.
    Saved lessons and forced tasks stay protected throughout this transaction-like
    search. A failed branch rolls back every displacement before trying another.
    """
    by_start = [{row[0]: row for row in rows} for rows in candidates]
    placed = [None] * len(tasks)
    teacher_busy = {}
    class_busy = {}
    subject_busy = defaultdict(Counter)
    for lesson in existing:
        owner = assignment_by_id.get(lesson.assignment_id)
        if owner is not None:
            teacher_busy[(owner.teacher_id, lesson.slot)] = -1
            class_busy[(owner.class_id, lesson.slot)] = -1
            subject_busy[(owner.class_id, owner.subject_id)][lesson.slot] += 1

    def write(index, row):
        owner = tasks[index][0]
        subject_slots = subject_busy[(owner.class_id, owner.subject_id)]
        previous = placed[index]
        if previous is not None:
            for slot in previous[2]:
                del teacher_busy[(owner.teacher_id, slot)]
                del class_busy[(owner.class_id, slot)]
                subject_slots[slot] -= 1
                if not subject_slots[slot]:
                    del subject_slots[slot]
        placed[index] = row
        if row is not None:
            for slot in row[2]:
                teacher_busy[(owner.teacher_id, slot)] = index
                class_busy[(owner.class_id, slot)] = index
                subject_slots[slot] += 1

    def respects_subject_limit(index, row, blockers):
        owner = tasks[index][0]
        limit = assignment_consecutive_limit(project, owner)
        pps = project.periods_per_session
        if limit >= pps:
            return True
        key = (owner.class_id, owner.subject_id)
        base = row[0] // pps * pps
        occupied = {slot for slot in subject_busy[key] if base <= slot < base + pps}
        # Candidate collisions will be removed before inserting this row.
        for blocker in blockers:
            other = tasks[blocker][0]
            if (other.class_id, other.subject_id) == key:
                occupied.difference_update(placed[blocker][2])
        occupied.update(row[1])
        run = 0
        for slot in range(base, base + pps):
            run = run + 1 if slot in occupied else 0
            if run > limit:
                return False
        return True

    for index, start in enumerate(genes):
        if start is not None:
            write(index, by_start[index][start])

    trail = []
    nodes = 0

    def change(index, row):
        trail.append((index, placed[index]))
        write(index, row)

    def rollback(mark):
        while len(trail) > mark:
            index, previous = trail.pop()
            write(index, previous)

    def insert(index, depth, protected):
        nonlocal nodes
        nodes += 1
        if nodes > node_limit or time.monotonic() >= deadline:
            return False
        owner = tasks[index][0]
        options = []
        for row in candidates[index]:
            blockers = set()
            for slot in row[2]:
                for occupant in (teacher_busy.get((owner.teacher_id, slot)), class_busy.get((owner.class_id, slot))):
                    if occupant is not None:
                        blockers.add(occupant)
            if any(blocker == -1 or blocker in protected or tasks[blocker][4] is not None for blocker in blockers):
                continue
            if blockers and depth == 0:
                continue
            if not respects_subject_limit(index, row, blockers):
                continue
            options.append((len(blockers), row[0], row, sorted(blockers)))
        options.sort(key=lambda item: (item[0], item[1]))
        for _count, _start, row, blockers in options:
            if nodes > node_limit or time.monotonic() >= deadline:
                return False
            mark = len(trail)
            for blocker in blockers:
                change(blocker, None)
            change(index, row)
            if all(insert(blocker, depth - 1, protected | {index}) for blocker in blockers):
                return True
            rollback(mark)
        return False

    for depth in (2, 4, 6, 8):
        pending = sorted((i for i, row in enumerate(placed) if row is None), key=lambda i: (len(candidates[i]), i))
        if not pending or nodes > node_limit or time.monotonic() >= deadline:
            break
        for index in pending:
            if insert(index, depth, frozenset()):
                trail.clear()

    lessons = []
    unscheduled = 0
    repaired_genes = []
    for index, row in enumerate(placed):
        task = tasks[index]
        repaired_genes.append(None if row is None else row[0])
        if row is None:
            unscheduled += task[2] - len(task[5])
        else:
            lessons.extend((task[0].id, slot, task[4] is not None, f"task:{index}") for slot in row[2])
    return {"lessons": lessons, "genes": repaired_genes, "unscheduled": unscheduled,
            "solver": "relocation_repair", "repair_nodes": nodes}
