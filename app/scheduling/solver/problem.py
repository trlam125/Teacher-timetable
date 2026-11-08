"""Prepare one shared scheduling problem for every search algorithm."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logic import fixed_group_validation_error, pop_matching_fixed_task
from app.models import (
    Assignment,
    FixedLesson,
    Lesson,
    Project,
    SchoolClass,
    Subject,
    Teacher,
)
from app.scheduling.rules import (
    all_slots,
    assignment_consecutive_limit,
    assignment_groups,
    assignment_requires_double,
    class_blocked_slots,
    fixed_row_size,
    parse_slots,
    pattern_completion_plan,
    required_double_block_state,
)

Task = tuple[Assignment, int, int, bool, int | None, tuple[int, ...], tuple[int, ...] | None]
Candidate = tuple[int, tuple[int, ...], tuple[int, ...], int, int, int]


@dataclass(slots=True)
class SchedulingProblem:
    project: Project
    periods_per_day: int
    assignments: list[Assignment]
    assignment_by_id: dict[int, Assignment]
    teachers: dict[int, Teacher]
    classes: dict[int, SchoolClass]
    subjects: dict[int, Subject]
    all_existing: list[Lesson]
    existing: list[Lesson]
    task_rows: list[Task]
    task_candidates: list[tuple[Candidate, ...]]
    slots: list[int]
    existing_teacher_slot: dict
    existing_class_slot: dict
    existing_teacher_day: dict
    existing_class_subject_day: dict
    existing_assignment_slots: dict
    existing_class_subject_slots: dict
    existing_css: dict


def build_problem(
    db: Session, p: Project, mode: str, target_assignment_ids: Optional[set[int]] = None,
) -> SchedulingProblem | dict:
    """Return cached tasks/candidates, or the existing structured input error."""
    assignments = db.scalars(
        select(Assignment).where(Assignment.project_id == p.id)
    ).all()
    assignment_by_id = {row.id: row for row in assignments}
    teachers = {
        x.id: x for x in db.scalars(select(Teacher).where(Teacher.project_id == p.id))
    }
    classes = {
        x.id: x
        for x in db.scalars(select(SchoolClass).where(SchoolClass.project_id == p.id))
    }
    subjects = {
        x.id: x for x in db.scalars(select(Subject).where(Subject.project_id == p.id))
    }
    all_existing = db.scalars(select(Lesson).where(Lesson.project_id == p.id)).all()
    relevant_assignments = (
        assignments
        if target_assignment_ids is None
        else [row for row in assignments if row.id in target_assignment_ids]
    )
    invalid_reference_ids = sorted(
        row.id
        for row in relevant_assignments
        if row.teacher_id not in teachers
        or row.class_id not in classes
        or row.subject_id not in subjects
    )
    if invalid_reference_ids:
        invalid_reference_id_set = set(invalid_reference_ids)
        missing = sum(
            max(1, int(row.periods_per_week or 0))
            for row in relevant_assignments
            if row.id in invalid_reference_id_set
        )
        return {
            "lessons": [],
            "unscheduled": missing,
            "score": missing * 10000,
            "invalid_assignments": invalid_reference_ids,
            "invalid_reference_assignments": invalid_reference_ids,
        }
    if mode == "missing":
        existing = list(all_existing)
    elif mode == "rebuild":
        existing = [lesson for lesson in all_existing if lesson.locked]
    elif mode == "full":
        existing = []
    else:
        raise ValueError(f"Chế độ xếp lịch không hợp lệ: {mode}")
    existing_slots = defaultdict(set)
    locked_slots = defaultdict(set)
    all_existing_by_assignment = defaultdict(list)
    for lesson in all_existing:
        all_existing_by_assignment[lesson.assignment_id].append(lesson)
    existing_by_assignment = defaultdict(list)
    for lesson in existing:
        existing_by_assignment[lesson.assignment_id].append(lesson)
    for lesson in existing:
        existing_slots[lesson.assignment_id].add(lesson.slot)
        if lesson.locked:
            locked_slots[lesson.assignment_id].add(lesson.slot)
    fixed_rows_by_assignment = defaultdict(list)
    for row in db.scalars(
        select(FixedLesson).where(FixedLesson.project_id == p.id)
    ).all():
        assignment = assignment_by_id.get(row.assignment_id)
        if assignment:
            size = fixed_row_size(
                p,
                assignment,
                row,
                all_existing_by_assignment[assignment.id],
            )
            fixed_rows_by_assignment[row.assignment_id].append((row.slot, size))
    invalid_fixed_assignment_ids = set()
    for assignment in assignments:
        fixed_error = fixed_group_validation_error(
            assignment_groups(assignment),
            fixed_rows_by_assignment[assignment.id],
            days=p.days,
            sessions=p.sessions,
            periods_per_session=p.periods_per_session,
        )
        if fixed_error and (
            target_assignment_ids is None or assignment.id in target_assignment_ids
        ):
            invalid_fixed_assignment_ids.add(assignment.id)
    global_blocked = parse_slots(p.blocked_slots_json)
    slots = all_slots(p)
    ppd = p.sessions * p.periods_per_session
    if not assignments:
        return {"lessons": [], "unscheduled": 0, "score": 0}

    task_rows = []
    invalid_assignment_ids = []
    for assignment in assignments:
        if (
            target_assignment_ids is not None
            and assignment.id not in target_assignment_ids
        ):
            continue
        if assignment.id in invalid_fixed_assignment_ids:
            continue

        task_index = 0
        if assignment_requires_double(assignment):
            # New required_double model: persisted block_id is authoritative.
            # Existing adjacency is never reinterpreted into another pair.
            current_lessons = (
                existing_by_assignment[assignment.id]
                if mode in {"missing", "rebuild"}
                else []
            )
            state = required_double_block_state(p, assignment, current_lessons)
            if not state["valid"]:
                invalid_assignment_ids.append(assignment.id)
                continue

            missing_counts = Counter(state["missing_sizes"])
            current_by_start_size = {
                (group["start"], group["size"]): group for group in state["groups"]
            }

            # Fixed rows are explicit blocks. If the corresponding locked block
            # is already part of the current base schedule, keep it. Otherwise
            # create one forced solver task at exactly that start.
            for fixed_slot, fixed_size in fixed_rows_by_assignment[assignment.id]:
                current_group = current_by_start_size.get((fixed_slot, fixed_size))
                if current_group is not None:
                    if not all(lesson.locked for lesson in current_group["lessons"]):
                        invalid_fixed_assignment_ids.add(assignment.id)
                        break
                    continue
                if missing_counts[fixed_size] <= 0:
                    invalid_fixed_assignment_ids.add(assignment.id)
                    break
                missing_counts[fixed_size] -= 1
                task_rows.append(
                    (
                        assignment,
                        task_index,
                        fixed_size,
                        True,
                        fixed_slot,
                        tuple(),
                        (fixed_slot,),
                    )
                )
                task_index += 1
            if assignment.id in invalid_fixed_assignment_ids:
                continue

            for size in (2, 1):
                for _ in range(missing_counts[size]):
                    task_rows.append(
                        (
                            assignment,
                            task_index,
                            size,
                            True,
                            None,
                            tuple(),
                            None,
                        )
                    )
                    task_index += 1
            continue

        current_slots = (
            existing_slots[assignment.id] if mode in {"missing", "rebuild"} else set()
        )
        plan = pattern_completion_plan(
            p,
            assignment,
            current_slots,
            fixed_groups=fixed_rows_by_assignment[assignment.id],
        )
        if plan is None:
            invalid_assignment_ids.append(assignment.id)
            continue
        pending = [dict(item) for item in plan]
        for fixed_slot, fixed_size in fixed_rows_by_assignment[assignment.id]:
            expected = set(range(fixed_slot, fixed_slot + fixed_size))
            if expected.issubset(locked_slots[assignment.id]):
                continue
            item = pop_matching_fixed_task(pending, fixed_slot, fixed_size)
            if item is None:
                invalid_fixed_assignment_ids.add(assignment.id)
                break
            task_rows.append(
                (
                    assignment,
                    task_index,
                    fixed_size,
                    False,
                    fixed_slot,
                    tuple(item["anchor_slots"]),
                    (fixed_slot,),
                )
            )
            task_index += 1
        if assignment.id in invalid_fixed_assignment_ids:
            continue
        for item in pending:
            task_rows.append(
                (
                    assignment,
                    task_index,
                    item["size"],
                    False,
                    None,
                    tuple(item["anchor_slots"]),
                    item["candidate_starts"],
                )
            )
            task_index += 1

    if invalid_assignment_ids or invalid_fixed_assignment_ids:
        affected_ids = set(invalid_assignment_ids).union(invalid_fixed_assignment_ids)
        missing = sum(
            max(0, assignment.periods_per_week - len(existing_slots[assignment.id]))
            for assignment in assignments
            if assignment.id in affected_ids
        )
        if affected_ids and missing == 0:
            # Không được trả unscheduled=0 khi chính dữ liệu hiện tại đã làm
            # pattern_completion_plan() thất bại (ví dụ dữ liệu cũ bị thừa tiết).
            missing = len(affected_ids)
        return {
            "lessons": [],
            "unscheduled": missing,
            "score": missing * 10000,
            "invalid_assignments": invalid_assignment_ids,
            "invalid_fixed_assignments": sorted(invalid_fixed_assignment_ids),
        }

    if not task_rows:
        return {"lessons": [], "unscheduled": 0, "score": 0}

    # Cache all immutable scheduling data once.  The former implementation
    # reparsed JSON and searched the assignment list inside every GA/exact
    # iteration, which becomes expensive on school-sized timetables.
    teacher_unavailable = {
        teacher_id: frozenset(parse_slots(teacher.unavailable_json))
        for teacher_id, teacher in teachers.items()
    }
    class_unavailable = {
        class_id: frozenset(class_blocked_slots(row))
        for class_id, row in classes.items()
    }
    slot_set = frozenset(slots)

    existing_teacher_slot = Counter()
    existing_class_slot = Counter()
    existing_teacher_day = Counter()
    existing_class_subject_day = Counter()
    existing_assignment_slots = defaultdict(set)
    existing_class_subject_slots = defaultdict(set)
    existing_css = Counter()
    for lesson in existing:
        assignment = assignment_by_id.get(lesson.assignment_id)
        if not assignment:
            continue
        day = lesson.slot // ppd
        existing_teacher_slot[(assignment.teacher_id, lesson.slot)] += 1
        existing_class_slot[(assignment.class_id, lesson.slot)] += 1
        existing_teacher_day[(assignment.teacher_id, day)] += 1
        existing_class_subject_day[
            (assignment.class_id, assignment.subject_id, day)
        ] += 1
        existing_assignment_slots[assignment.id].add(lesson.slot)
        existing_class_subject_slots[(assignment.class_id, assignment.subject_id)].add(
            lesson.slot
        )
        existing_css[(assignment.class_id, assignment.subject_id, lesson.slot)] += 1

    starts_by_size = {}

    def start_pool(size: int):
        pool = starts_by_size.get(size)
        if pool is None:
            pool = tuple(
                slot
                for slot in slots
                if (slot % ppd) % p.periods_per_session + size <= p.periods_per_session
            )
            starts_by_size[size] = pool
        return pool

    def static_candidates_for_task(task):
        """Build immutable candidates once for CP-SAT, GA and exact search.

        Only constraints that never change during search are checked here.
        Dynamic collisions/workload created by other candidate choices remain in
        the individual solvers.
        """
        (
            assignment,
            group_index,
            size,
            explicit,
            forced,
            anchor_slots,
            planned_starts,
        ) = task
        anchor = frozenset(anchor_slots)
        missing_size = size - len(anchor)
        if forced is not None:
            candidate_pool = (forced,)
        elif planned_starts is not None:
            candidate_pool = tuple(planned_starts)
        else:
            candidate_pool = start_pool(size)

        unavailable = (
            teacher_unavailable[assignment.teacher_id]
            | class_unavailable[assignment.class_id]
            | frozenset(global_blocked)
        )
        subject = subjects[assignment.subject_id]
        max_run = assignment_consecutive_limit(p, assignment)
        static_subject_slots = existing_class_subject_slots[
            (assignment.class_id, assignment.subject_id)
        ]
        rows = []
        for slot in sorted(set(candidate_pool)):
            if slot not in slot_set:
                continue
            day = slot // ppd
            position = slot % ppd
            session = position // p.periods_per_session
            period = position % p.periods_per_session
            if period + size > p.periods_per_session:
                continue
            group_slots = tuple(range(slot, slot + size))
            group_set = frozenset(group_slots)
            if anchor and not anchor.issubset(group_set):
                continue
            new_slots = tuple(
                candidate for candidate in group_slots if candidate not in anchor
            )
            if len(new_slots) != missing_size:
                continue
            if any(
                candidate // ppd != day
                or (candidate % ppd) // p.periods_per_session != session
                for candidate in group_slots
            ):
                continue
            if any(candidate in unavailable for candidate in new_slots):
                continue
            if any(
                existing_teacher_slot[(assignment.teacher_id, candidate)]
                or existing_class_slot[(assignment.class_id, candidate)]
                for candidate in new_slots
            ):
                continue
            if (
                existing_teacher_day[(assignment.teacher_id, day)] + missing_size
                > ppd
            ):
                continue

            # Prune candidates that already violate max_consecutive even before
            # any new task is placed.  The dynamic check still runs later for
            # combinations of multiple tasks.
            existing_periods = {
                candidate % p.periods_per_session
                for candidate in static_subject_slots
                if candidate // ppd == day
                and (candidate % ppd) // p.periods_per_session == session
            }
            run = sorted(existing_periods | set(range(period, period + size)))
            longest = current = 1
            for left, right in zip(run, run[1:]):
                current = current + 1 if right == left + 1 else 1
                longest = max(longest, current)
            if longest > max_run:
                continue

            rows.append((slot, group_slots, new_slots, day, session, period))
        return tuple(rows)

    # MRV: schedule the tasks with the fewest real candidates first.  Forced
    # tasks remain at the front.  This order is shared by all fallback solvers.
    task_candidate_pairs = [
        (task, static_candidates_for_task(task)) for task in task_rows
    ]
    task_candidate_pairs.sort(
        key=lambda item: (
            0 if item[0][4] is not None else 1,
            len(item[1]),
            -(item[0][2] - len(item[0][5])),
            -(
                len(teacher_unavailable[item[0][0].teacher_id])
                + len(class_unavailable[item[0][0].class_id])
            ),
            item[0][0].id,
            item[0][1],
        )
    )
    task_rows = [item[0] for item in task_candidate_pairs]
    task_candidates = [item[1] for item in task_candidate_pairs]

    return SchedulingProblem(
        project=p, periods_per_day=ppd,
        assignments=assignments,
        assignment_by_id=assignment_by_id,
        teachers=teachers,
        classes=classes,
        subjects=subjects,
        all_existing=all_existing,
        existing=existing,
        task_rows=task_rows,
        task_candidates=task_candidates,
        slots=slots,
        existing_teacher_slot=existing_teacher_slot,
        existing_class_slot=existing_class_slot,
        existing_teacher_day=existing_teacher_day,
        existing_class_subject_day=existing_class_subject_day,
        existing_assignment_slots=existing_assignment_slots,
        existing_class_subject_slots=existing_class_subject_slots,
        existing_css=existing_css,
    )
