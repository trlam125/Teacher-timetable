from __future__ import annotations

import logging
import os
import random
import time
from collections import Counter, defaultdict
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logic import fixed_group_validation_error, pop_matching_fixed_task
from app.models import (
    Assignment, FixedLesson, Lesson, Project, SchoolClass, Subject, Teacher,
)
from app.scheduling.rules import (
    all_slots, assignment_groups, assignment_prefers_double,
    assignment_requires_double, fixed_row_size, parse_slots,
    pattern_completion_plan, preferred_double_pair_count,
    required_double_block_state,
)

logger = logging.getLogger("smart_tkb")


def _teacher_idle_gaps(p: Project, busy_slots) -> int:
    """Count idle periods inside each day/session, never across sessions."""
    ppd = p.sessions * p.periods_per_session
    busy = set(busy_slots)
    gaps = 0
    for day in range(p.days):
        day_base = day * ppd
        for session in range(p.sessions):
            start = day_base + session * p.periods_per_session
            end = start + p.periods_per_session
            periods = sorted(slot - start for slot in busy if start <= slot < end)
            if periods:
                gaps += periods[-1] - periods[0] + 1 - len(periods)
    return gaps


def _schedule_soft_score(
    p: Project,
    assignments: list[Assignment],
    assignment_by_id: dict[int, Assignment],
    final_slots: dict[int, set[int]],
) -> float:
    """One canonical soft-score formula shared by every solver.

    Lower is better. Hard feasibility is intentionally not encoded here; callers
    keep unscheduled periods as the dominant lexicographic criterion.
    """
    ppd = p.sessions * p.periods_per_session
    score = 0.0
    teacher_slots = defaultdict(set)

    for assignment in assignments:
        slots_for_assignment = set(final_slots.get(assignment.id, set()))
        if assignment_prefers_double(assignment):
            formed_pairs = preferred_double_pair_count(p, slots_for_assignment)
            target_pairs = int(assignment.periods_per_week or 0) // 2
            score += max(0, target_pairs - formed_pairs) * 14

        day_counts = Counter(slot // ppd for slot in slots_for_assignment)
        score += sum(max(0, count - 1) * 8 for count in day_counts.values())

        owner = assignment_by_id.get(assignment.id)
        if owner:
            teacher_slots[owner.teacher_id].update(slots_for_assignment)

    for busy in teacher_slots.values():
        score += _teacher_idle_gaps(p, busy) * 2
    return score


def _solver_timeout_seconds() -> float:
    try:
        value = float(os.getenv("SCHEDULE_SOLVER_TIMEOUT_SECONDS", "15"))
    except (TypeError, ValueError):
        value = 15.0
    return max(3.0, min(60.0, value))


def ga_schedule(
    db: Session,
    p: Project,
    mode: str,
    tries: int = 120,
    target_assignment_ids: Optional[set[int]] = None,
    deadline: float | None = None,
):
    if deadline is None:
        deadline = time.monotonic() + _solver_timeout_seconds()

    def time_left() -> float:
        return max(0.0, deadline - time.monotonic())

    def deadline_hit(reserve: float = 0.0) -> bool:
        return time_left() <= reserve
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
    existing_counts = Counter(x.assignment_id for x in existing)
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
            p, assignment, current_slots,
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
        class_id: frozenset(parse_slots(row.unavailable_json))
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
        existing_class_subject_day[(assignment.class_id, assignment.subject_id, day)] += 1
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
                if (slot % ppd) % p.periods_per_session + size
                <= p.periods_per_session
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
        max_run = max(1, int(subject.max_consecutive or 1))
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
                > teachers[assignment.teacher_id].max_periods_day
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

    def cp_sat_primary():
        """Run CP-SAT in two phases: complete hard solution, then soft optimize.

        Phase 1 has no soft objective and requires every task to be placed. Phase
        2 reuses that complete timetable as a hint and spends only the remaining
        request-wide budget on the canonical soft objective.
        """
        try:
            from ortools.sat.python import cp_model
        except ImportError:
            logger.warning("OR-Tools is not installed; falling back to GA scheduler")
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

        for index, (task, candidates) in enumerate(zip(task_rows, task_candidates)):
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
            # Phase 1 is pure hard feasibility: every task must be placed.  We
            # do not create optional/unscheduled variables here because they
            # make CP-SAT spend time optimizing partial schedules before it has
            # proved that a complete timetable exists.
            if not rows:
                return {
                    "lessons": [],
                    "unscheduled": max(1, missing_size),
                    "score": max(1, missing_size) * 10000,
                    "solver": "cp_sat_feasibility",
                    "proven_infeasible": True,
                }
            model.Add(option_sum == 1)
            unscheduled = None
            start_expr = sum(row[0] * row[6] for row in rows)

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
                <= teachers[teacher_id].max_periods_day
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
            max_run = max(1, int(subject.max_consecutive or 1))
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
                            1 if right in existing_assignment_slots[assignment.id] else 0
                        )
                        if not (left_fixed or left_vars) or not (right_fixed or right_vars):
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
                        possible.append(bool(
                            existing_teacher_slot[(teacher_id, slot)]
                            or slot_var_by_teacher[(teacher_id, slot)]
                        ))
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
                        model.Add(
                            gap >= before + after - occupancy[period] - 1
                        )
                        objective_terms.append(2 * gap)

        total_budget = min(_solver_timeout_seconds(), time_left())

        def make_solver(time_limit: float):
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = max(0.05, time_limit)
            solver.parameters.num_search_workers = max(1, min(8, os.cpu_count() or 1))
            solver.parameters.random_seed = 42
            return solver

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
                for start, new_slots, _group_slots, _day, _session, _period, var in rows:
                    if solver.Value(var):
                        chosen_starts[index] = start
                        for candidate in new_slots:
                            lessons.append((assignment.id, candidate, forced is not None, f"task:{index}"))
                            final_slots[assignment.id].add(candidate)
                        break

            soft_score = (
                unscheduled_count * 10000.0
                + _schedule_soft_score(
                    p, assignments, assignment_by_id, final_slots
                )
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

        # Phase 1: pure hard-feasibility search, no soft objective.  Reserve part
        # of the request-wide deadline for GA/backtracking only when CP-SAT fails
        # to find a complete schedule in time.
        hard_time = min(total_budget, max(0.2, total_budget * 0.60))
        solver = make_solver(hard_time)
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            if status == cp_model.INFEASIBLE:
                missing = sum(
                    max(1, task[2] - len(task[5])) for task in task_rows
                )
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
        remaining = time_left()
        if not objective_terms or remaining <= 0.10:
            return hard_result
        for var in all_option_vars:
            model.AddHint(var, solver.Value(var))
        model.Minimize(sum(objective_terms))

        optimize_solver = make_solver(remaining)
        optimize_status = optimize_solver.Solve(model)
        if optimize_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            optimized = extract_result(
                optimize_solver, optimize_status, "cp_sat_optimize"
            )
            optimized["wall_time"] = round(
                hard_result.get("wall_time", 0) + optimize_solver.WallTime(), 3
            )
            return optimized

        hard_result["search_limited"] = True
        hard_result["wall_time"] = round(
            hard_result.get("wall_time", 0) + optimize_solver.WallTime(), 3
        )
        return hard_result

    cp_result = cp_sat_primary()
    if cp_result is not None and cp_result["unscheduled"] == 0:
        return cp_result
    if cp_result is not None and cp_result.get("proven_infeasible"):
        return cp_result

    candidate_by_start = [
        {row[0]: row for row in candidates} for candidates in task_candidates
    ]

    def evaluate(genes: list[int | None]):
        """Decode one chromosome into a timetable candidate.

        The chromosome now has real control over placement: each non-null gene
        is attempted at that exact start first. Only genes that cannot coexist
        with already accepted genes enter a bounded greedy repair phase. This is
        materially different from the old decoder, where every task scanned all
        candidates and the gene merely added a tiny soft score.
        """
        teacher_busy = defaultdict(set)
        class_busy = defaultdict(set)
        assignment_busy = defaultdict(set)
        teacher_day = Counter()
        class_sub_day = Counter()
        class_sub_slots = defaultdict(set)
        placed = []
        chosen_starts = [None] * len(task_rows)

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

        def feasible(index: int, row) -> bool:
            assignment, _group_index, size, _explicit, _forced, anchor_slots, _planned = (
                task_rows[index]
            )
            slot, _group_slots, new_slots, day, session, period = row
            missing_size = size - len(anchor_slots)
            if any(
                candidate in teacher_busy[assignment.teacher_id]
                or candidate in class_busy[assignment.class_id]
                for candidate in new_slots
            ):
                return False
            if (
                teacher_day[(assignment.teacher_id, day)] + missing_size
                > teachers[assignment.teacher_id].max_periods_day
            ):
                return False
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
            return longest <= max(
                1, int(subjects[assignment.subject_id].max_consecutive or 1)
            )

        def row_soft_score(index: int, row, gene: int | None) -> float:
            assignment, _group_index, size, _explicit, _forced, _anchor, _planned = (
                task_rows[index]
            )
            slot, _group_slots, new_slots, day, _session, period = row
            score = class_sub_day[
                (assignment.class_id, assignment.subject_id, day)
            ] * 8 + sum(
                (candidate % p.periods_per_session) * 0.15
                for candidate in new_slots
            )
            neighbors = []
            if period > 0:
                neighbors.append(slot - 1)
            if period + size < p.periods_per_session:
                neighbors.append(slot + size)
            for neighbor in neighbors:
                if neighbor in teacher_busy[assignment.teacher_id]:
                    score -= 1.2
                if (
                    assignment_prefers_double(assignment)
                    and neighbor in assignment_busy[assignment.id]
                ):
                    score -= 7.0
            if gene is not None and slot != gene:
                # Repair should stay near the inherited gene when several
                # alternatives are otherwise similar, but this is only a
                # tiebreaking repair cost -- not the chromosome semantics.
                score += abs(slot - gene) * 0.12
            return score

        def place(index: int, row):
            assignment, _group_index, _size, _explicit, forced, _anchor, _planned = (
                task_rows[index]
            )
            slot, _group_slots, new_slots, day, _session, _period = row
            chosen_starts[index] = slot
            for candidate in new_slots:
                teacher_busy[assignment.teacher_id].add(candidate)
                class_busy[assignment.class_id].add(candidate)
                assignment_busy[assignment.id].add(candidate)
                class_sub_slots[(assignment.class_id, assignment.subject_id, day)].add(
                    candidate % ppd
                )
                placed.append((assignment.id, candidate, forced is not None, f"task:{index}"))
            teacher_day[(assignment.teacher_id, day)] += len(new_slots)
            class_sub_day[(assignment.class_id, assignment.subject_id, day)] += len(
                new_slots
            )

        pending = []
        for index, task in enumerate(task_rows):
            forced = task[4]
            gene = forced if forced is not None else genes[index]
            row = candidate_by_start[index].get(gene) if gene is not None else None
            if row is not None and feasible(index, row):
                place(index, row)
            else:
                pending.append(index)

        # Repair only the genes that could not be honored. Dynamic MRV reduces
        # the chance that a flexible repair steals the last slot from a hard one.
        unresolved = []
        pending = set(pending)
        while pending:
            selected_index = None
            selected_options = None
            for index in tuple(pending):
                forced = task_rows[index][4]
                gene = forced if forced is not None else genes[index]
                candidates = task_candidates[index]
                if forced is not None:
                    forced_row = candidate_by_start[index].get(forced)
                    candidates = (forced_row,) if forced_row is not None else ()
                options = [row for row in candidates if feasible(index, row)]
                if not options:
                    unresolved.append(index)
                    pending.remove(index)
                    continue
                if selected_options is None or len(options) < len(selected_options):
                    selected_index = index
                    selected_options = options
                    if len(options) == 1:
                        break
            if selected_index is None:
                continue
            pending.remove(selected_index)
            forced = task_rows[selected_index][4]
            gene = forced if forced is not None else genes[selected_index]
            best_row = min(
                selected_options,
                key=lambda row: (
                    row_soft_score(selected_index, row, gene),
                    row[0],
                ),
            )
            place(selected_index, best_row)

        unscheduled = sum(
            max(1, task_rows[index][2] - len(task_rows[index][5]))
            for index in unresolved
        )
        final_slots = defaultdict(set)
        for lesson in existing:
            final_slots[lesson.assignment_id].add(lesson.slot)
        for assignment_id, slot, _locked, _block_token in placed:
            final_slots[assignment_id].add(slot)
        score = unscheduled * 10000 + _schedule_soft_score(
            p, assignments, assignment_by_id, final_slots
        )
        return {
            "lessons": placed,
            "unscheduled": unscheduled,
            "score": round(score, 2),
            "genes": chosen_starts,
            "solver": "ga_fallback",
        }

    def genes_from_candidate(candidate):
        genes = list(candidate.get("genes", []))
        if len(genes) != len(task_rows):
            genes = [None] * len(task_rows)
        return genes

    def random_gene(index: int, task):
        forced = task[4]
        if forced is not None:
            return forced
        pool = [row[0] for row in task_candidates[index]]
        return random.choice(pool) if pool else None

    def mutate(genes, mutation_rate: float = 0.16):
        child = genes[:]
        for index, task in enumerate(task_rows):
            forced = task[4]
            if forced is not None:
                child[index] = forced
                continue
            if random.random() < mutation_rate:
                # Most mutations choose another real candidate. A small share
                # clears the gene and lets the repair decoder explore freely.
                child[index] = (
                    random_gene(index, task) if random.random() < 0.92 else None
                )
        return child

    def crossover(left, right):
        # Uniform crossover preserves useful independent placement decisions
        # better than a single cut because MRV sorting groups unrelated tasks.
        child = []
        for index, task in enumerate(task_rows):
            forced = task[4]
            if forced is not None:
                child.append(forced)
            else:
                child.append(left[index] if random.random() < 0.5 else right[index])
        return child

    def exact_fallback(node_limit: int):
        """Try an exact MRV backtracking pass for small/medium hard cases."""
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
            for slot, group_slots, new_slots, day, session, period in task_candidates[index]:
                if any(
                    candidate in teacher_busy[assignment.teacher_id]
                    or candidate in class_busy[assignment.class_id]
                    for candidate in new_slots
                ):
                    continue
                if (
                    teacher_day[(assignment.teacher_id, day)] + missing_size
                    > teachers[assignment.teacher_id].max_periods_day
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
                    1, int(subjects[assignment.subject_id].max_consecutive or 1)
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
            lessons.extend((assignment_id, slot, locked, f"task:{index}") for slot in new_slots)
        final_slots = defaultdict(set)
        for lesson in existing:
            final_slots[lesson.assignment_id].add(lesson.slot)
        for assignment_id, slot, _locked, _block_token in lessons:
            final_slots[assignment_id].add(slot)
        soft_score = _schedule_soft_score(
            p, assignments, assignment_by_id, final_slots
        )
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

    # GA fallback: keep the total search bounded, but maintain enough diversity
    # for medium/large projects where CP-SAT times out or is unavailable.
    population_size = max(24, min(48, max(24, len(task_rows) // 2 + 14)))
    generations = max(20, min(55, max(tries // 4, 24)))
    elite_count = max(3, population_size // 6)

    def candidate_key(candidate):
        # Hard feasibility is lexicographically dominant over every soft score.
        return (candidate["unscheduled"], candidate["score"])

    seed_candidate = evaluate([None] * len(task_rows))
    best_candidate = seed_candidate
    if cp_result is not None and candidate_key(cp_result) < candidate_key(best_candidate):
        best_candidate = cp_result

    population = [genes_from_candidate(seed_candidate)]
    if cp_result is not None:
        cp_genes = genes_from_candidate(cp_result)
        if cp_genes != population[0]:
            population.append(cp_genes)
    while len(population) < population_size:
        population.append(
            [random_gene(index, task) for index, task in enumerate(task_rows)]
        )

    def evaluate_population(items):
        result = []
        for genes in items:
            if result and deadline_hit(0.05):
                break
            candidate = evaluate(genes)
            # Lamarckian repair: successful repaired placements become the
            # chromosome inherited by the next generation instead of throwing
            # that information away and keeping the pre-repair genotype.
            result.append((candidate, genes_from_candidate(candidate)))
        if not result:
            result.append((best_candidate, genes_from_candidate(best_candidate)))
        result.sort(key=lambda item: candidate_key(item[0]))
        return result

    def tournament_pick(evaluated, size: int = 4):
        sample_size = min(size, len(evaluated))
        contenders = random.sample(evaluated, sample_size)
        contenders.sort(key=lambda item: candidate_key(item[0]))
        return contenders[0][1]

    evaluated = evaluate_population(population)
    if candidate_key(evaluated[0][0]) < candidate_key(best_candidate):
        best_candidate = evaluated[0][0]

    stagnant_generations = 0
    for generation in range(generations):
        if deadline_hit(0.08):
            break
        previous_best = candidate_key(best_candidate)
        elites = [genes[:] for _candidate, genes in evaluated[:elite_count]]
        next_population = elites

        # Increase exploration after stagnation instead of repeatedly crossing
        # nearly identical elites. Random immigrants preserve search diversity.
        mutation_rate = min(0.34, 0.14 + stagnant_generations * 0.025)
        immigrant_rate = min(0.22, 0.08 + stagnant_generations * 0.02)
        seen = {tuple(genes) for genes in next_population}
        attempts = 0
        while len(next_population) < population_size:
            if deadline_hit(0.05):
                break
            attempts += 1
            if random.random() < immigrant_rate:
                child = [
                    random_gene(index, task)
                    for index, task in enumerate(task_rows)
                ]
            else:
                parent1 = tournament_pick(evaluated)
                parent2 = tournament_pick(evaluated)
                child = mutate(
                    crossover(parent1, parent2),
                    mutation_rate=mutation_rate,
                )
            key = tuple(child)
            # Avoid a population collapse, but never loop forever if the search
            # space itself is tiny.
            if key in seen and attempts < population_size * 8:
                continue
            seen.add(key)
            next_population.append(child)

        evaluated = evaluate_population(next_population)
        if candidate_key(evaluated[0][0]) < candidate_key(best_candidate):
            best_candidate = evaluated[0][0]

        if candidate_key(best_candidate) < previous_best:
            stagnant_generations = 0
        else:
            stagnant_generations += 1

        # Once a complete solution exists, a few additional generations can
        # improve soft quality; no need to spend the whole fallback budget.
        if (
            best_candidate["unscheduled"] == 0
            and generation >= 8
            and stagnant_generations >= 6
        ):
            break

    if best_candidate["unscheduled"] > 0:
        missing_periods = sum(task[2] - len(task[5]) for task in task_rows)
        # Python backtracking is useful only for genuinely small residual
        # problems.  Larger cases stay with CP-SAT/GA and respect the same
        # request-wide deadline instead of exploring hundreds of thousands of
        # nodes after the solver budget has already expired.
        exact_allowed = (
            len(task_rows) <= 24
            and missing_periods <= 36
            and not deadline_hit(0.25)
        )
        if exact_allowed:
            node_limit = min(100000, max(20000, tries * 400))
            exact_result, exhausted, nodes = exact_fallback(node_limit)
            if exact_result is not None:
                return exact_result
            best_candidate["proven_infeasible"] = exhausted
            best_candidate["search_limited"] = not exhausted
            best_candidate["exact_nodes"] = nodes
        else:
            best_candidate["proven_infeasible"] = False
            best_candidate["search_limited"] = True
    return best_candidate

def solve_missing(
    db: Session,
    p: Project,
    tries=120,
    target_assignment_ids: Optional[set[int]] = None,
    deadline: float | None = None,
):
    """Giữ nguyên lịch hiện có và chỉ xếp phần còn thiếu của các phân công đích."""
    return ga_schedule(
        db,
        p,
        mode="missing",
        tries=tries,
        target_assignment_ids=target_assignment_ids,
        deadline=deadline,
    )

def solve_rebuild(
    db: Session, p: Project, tries=220, deadline: float | None = None
):
    """Giữ tiết cố định, xếp lại toàn bộ phần còn lại."""
    return ga_schedule(db, p, mode="rebuild", tries=tries, deadline=deadline)

def solve(db: Session, p: Project, tries=80, deadline: float | None = None):
    return ga_schedule(db, p, mode="full", tries=tries, deadline=deadline)
