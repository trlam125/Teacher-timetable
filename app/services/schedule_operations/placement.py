from __future__ import annotations

from app.logic import schedule_validation_peers
from app.models import Assignment, Lesson, Project, SchoolClass, Subject, Teacher
from app.scheduling.rules import all_slots, class_grade_blocked_slots, parse_slots
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import Optional


def lesson_slot_error(
    db: Session,
    project: Project,
    assignment: Assignment,
    slot: int,
    exclude_lesson_id: Optional[int] = None,
    *,
    target_locked: bool = False,
):
    if slot not in all_slots(project):
        return "Ô thời khóa biểu không hợp lệ."
    if slot in parse_slots(project.blocked_slots_json):
        return "Tiết này đã bị khóa toàn trường và không được xếp lịch."
    teacher = db.get(Teacher, assignment.teacher_id)
    school_class = db.get(SchoolClass, assignment.class_id)
    subject = db.get(Subject, assignment.subject_id)
    if not teacher or not school_class or not subject:
        return "Phân công không còn đầy đủ lớp, môn hoặc giáo viên."
    if slot in parse_slots(teacher.unavailable_json):
        return "Giáo viên không thể dạy ở tiết này theo ràng buộc chính thức."
    if slot in class_grade_blocked_slots(school_class):
        return "Tiết này đã bị khóa theo khối của lớp và không được xếp lịch."
    if slot in parse_slots(school_class.unavailable_json):
        return "Lớp không học ở tiết này."
    existing_lessons = db.scalars(
        select(Lesson).where(Lesson.project_id == project.id)
    ).all()
    existing_lessons = [
        lesson for lesson in existing_lessons if lesson.id != exclude_lesson_id
    ]
    existing_lessons = schedule_validation_peers(
        existing_lessons,
        target_locked=target_locked,
    )
    for lesson in existing_lessons:
        if lesson.slot != slot:
            continue
        other = db.get(Assignment, lesson.assignment_id)
        if other and (
            other.class_id == assignment.class_id
            or other.teacher_id == assignment.teacher_id
        ):
            return "Ô đích bị trùng lớp hoặc giáo viên."
    return None
