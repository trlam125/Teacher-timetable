from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Assignment, FixedLesson, Grade, Lesson, Project, SchedulerRunDiagnostic, SchoolClass, Subject, Teacher
from app.scheduling.rules import all_slots, assignment_requires_double, class_blocked_slots, next_required_double_block_size, parse_slots
from app.scheduling.solver.diagnostics import scheduler_runtime_diagnostics
from app.services.schedule_operations.feasibility import assignment_completion_feasible, assignment_feasibility_context
from app.services.schedule_operations.validation import schedule_integrity_report


def record_scheduler_run(db: Session, project_id: int, search: dict, outcome: dict) -> None:
    """Keep one persisted run per project, shared between server workers."""
    row = db.get(SchedulerRunDiagnostic, project_id)
    if row is None:
        row = SchedulerRunDiagnostic(project_id=project_id)
        db.add(row)
    row.recorded_at = datetime.now(timezone.utc).isoformat()
    row.report_json = json.dumps({"search": search, "outcome": outcome}, ensure_ascii=False)


def _slot_label(project: Project, slot: int) -> str:
    day, inside = divmod(slot, project.sessions * project.periods_per_session)
    session, period = divmod(inside, project.periods_per_session)
    day_name = f"Thứ {day + 2}" if day < 6 else "Chủ nhật"
    session_name = "buổi học" if project.sessions == 1 else "sáng" if session == 0 else "chiều"
    return f"{day_name}, {session_name}, tiết {period + 1}"


def build_scheduler_diagnostics(db: Session, project: Project) -> dict:
    def rows(model):
        return db.scalars(select(model).where(model.project_id == project.id)).all()

    assignments = {row.id: row for row in rows(Assignment)}
    lessons = rows(Lesson)
    classes = {row.id: row for row in rows(SchoolClass)}
    teachers = {row.id: row for row in rows(Teacher)}
    subjects = {row.id: row for row in rows(Subject)}
    grades = rows(Grade)
    fixed_rows = rows(FixedLesson)
    fixed_by_assignment = defaultdict(list)
    lessons_by_assignment = defaultdict(list)
    class_busy = defaultdict(set)
    teacher_busy = defaultdict(list)
    for row in fixed_rows:
        fixed_by_assignment[row.assignment_id].append(row)
    for lesson in lessons:
        lessons_by_assignment[lesson.assignment_id].append(lesson)
        owner = assignments.get(lesson.assignment_id)
        if owner is not None:
            class_busy[owner.class_id].add(lesson.slot)
            teacher_busy[(owner.teacher_id, lesson.slot)].append(owner)
    snapshot = {"teachers": teachers, "classes": classes, "subjects": subjects,
                "assignments": assignments, "lessons": lessons, "fixed_by_assignment": fixed_by_assignment}
    maximum_slots = set(all_slots(project))
    global_blocked = parse_slots(project.blocked_slots_json)
    missing = []
    for assignment in assignments.values():
        current = lessons_by_assignment[assignment.id]
        remaining = int(assignment.periods_per_week) - len(current)
        if remaining <= 0:
            continue
        school_class = classes.get(assignment.class_id)
        teacher = teachers.get(assignment.teacher_id)
        subject = subjects.get(assignment.subject_id)
        detail = {
            "assignment_id": assignment.id,
            "class_name": school_class.name if school_class else "?",
            "teacher_name": teacher.name if teacher else "?",
            "subject_name": subject.name if subject else "?",
            "required_periods": assignment.periods_per_week,
            "scheduled_periods": len(current),
            "missing_periods": remaining,
            "valid_slot_count": 0,
            "empty_class_slot_count": 0,
            "candidate_slots": [],
        }
        missing.append(detail)
        if school_class is None or teacher is None or subject is None:
            detail["message"] = "Phân công thiếu dữ liệu lớp, giáo viên hoặc môn học."
            continue
        size = next_required_double_block_size(project, assignment, current) if assignment_requires_double(assignment) else 1
        if size is None or size == 0:
            detail["message"] = "Cấu trúc cặp tiết đôi cần được kiểm tra trước khi xếp tiếp."
            continue
        context = assignment_feasibility_context(db, project, assignment, snapshot=snapshot)
        current_slots = [row.slot for row in current]
        class_allowed = maximum_slots - global_blocked - class_blocked_slots(school_class) - class_busy[school_class.id]
        avoid = parse_slots(teacher.unavailable_json)
        candidates = []
        for slot in sorted(class_allowed):
            target = list(range(slot, slot + size))
            if slot % project.periods_per_session + size > project.periods_per_session or not set(target).issubset(class_allowed):
                continue
            detail["empty_class_slot_count"] += 1
            valid = assignment_completion_feasible(db, project, assignment, [*current_slots, *target], allow_partial=True, context=context)
            if valid:
                detail["valid_slot_count"] += 1
            reasons = []
            if avoid.intersection(target):
                reasons.append("Giáo viên đã đặt tránh thời điểm này.")
            conflicts = {(owner.id, candidate) for candidate in target for owner in teacher_busy[(teacher.id, candidate)]}
            for owner_id, candidate in sorted(conflicts):
                owner = assignments[owner_id]
                other_class = classes.get(owner.class_id)
                other_subject = subjects.get(owner.subject_id)
                reasons.append(f"Giáo viên đang dạy {other_subject.name if other_subject else '?'} lớp {other_class.name if other_class else '?'} ({_slot_label(project, candidate)}).")
            if not valid and not reasons:
                reasons.append("Vị trí này chưa thỏa cấu trúc cụm tiết hoặc các tiết cố định của phân công.")
            candidates.append({"slot": slot, "label": _slot_label(project, slot), "group_size": size, "valid": valid, "reasons": reasons})
        # Show useful valid positions first and bound report size for empty schedules.
        candidates.sort(key=lambda item: (not item["valid"], item["slot"]))
        detail["candidate_slots"] = candidates[:8]
        detail["omitted_candidate_count"] = max(0, len(candidates) - 8)
        detail["message"] = (
            f"Có {detail['valid_slot_count']} vị trí hợp lệ để xếp tiếp."
            if detail["valid_slot_count"] else
            "Các ô trống của lớp đều bị chặn bởi lịch hoặc ràng buộc hiện tại; có thể cần xếp lại phần không cố định."
            if candidates else
            "Lớp không còn ô trống phù hợp sau khi áp dụng khóa lịch, tiết tránh và số tiết liên tiếp."
        )
    missing.sort(key=lambda row: (row["class_name"], row["subject_name"], row["teacher_name"]))
    integrity = schedule_integrity_report(db, project)
    last = db.get(SchedulerRunDiagnostic, project.id)
    latest = {"recorded_at": last.recorded_at, **json.loads(last.report_json)} if last is not None else None
    return {
        "project_id": project.id,
        "project_name": project.name,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        **scheduler_runtime_diagnostics(),
        "summary": {
            "required_periods": sum(int(row.periods_per_week) for row in assignments.values()),
            "scheduled_periods": len(lessons),
            "missing_periods": sum(row["missing_periods"] for row in missing),
            "assignment_count": len(assignments),
            "locked_lessons": sum(bool(row.locked) for row in lessons),
            "fixed_blocks": len(fixed_rows),
            "grades_with_locks": sum(bool(parse_slots(row.blocked_slots_json)) for row in grades),
            "teachers_with_avoid_slots": sum(bool(parse_slots(row.unavailable_json)) for row in teachers.values()),
            "classes_with_avoid_slots": sum(bool(parse_slots(row.unavailable_json)) for row in classes.values()),
            "valid": integrity["valid"],
            "complete": integrity["complete"],
            "message": integrity["message"],
        },
        "latest_run": latest,
        "unscheduled_assignments": missing,
        "integrity": integrity,
    }
