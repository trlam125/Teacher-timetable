from __future__ import annotations

from fastapi import APIRouter
from app.services.runtime import *
from app.services.schedule_operations.feasibility import ensure_pinned_assignments_feasible

router = APIRouter()


def displacement_confirmation(removed_ids: set[int], payload):
    """Require confirmation for the exact lesson rows that will be displaced.

    The lesson IDs form a confirmation fingerprint. If another request changes
    the schedule between preview and confirmation, the fingerprint changes and
    the user must confirm the new impact instead of approving by count only.
    """
    affected_ids = sorted(set(removed_ids))
    if not affected_ids:
        return None

    confirmed_ids = sorted(set(payload.confirmed_affected_lesson_ids or []))
    if payload.confirm_displacement is True and confirmed_ids == affected_ids:
        return None

    return JSONResponse(
        {
            "ok": False,
            "requires_confirmation": True,
            "affected_lessons": len(affected_ids),
            "affected_lesson_ids": affected_ids,
            "message": (
                f"Thay đổi này sẽ đưa {len(affected_ids)} tiết đang xếp về khay. "
                "Bạn có muốn tiếp tục không?"
            ),
        },
        409,
    )


@router.post("/api/projects/{pid}/constraints")
def constraints(
    pid: int,
    payload: ConstraintIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    p = get_project_for_update(pid, user, db)
    if payload.entity_type not in {"teacher", "class"}:
        raise HTTPException(400, "Loại ràng buộc không hợp lệ")
    model = Teacher if payload.entity_type == "teacher" else SchoolClass
    obj = db.get(model, payload.entity_id)
    if not obj or obj.project_id != pid:
        raise HTTPException(404)
    slots = set(valid_slots(p, payload.slots))
    assignments = db.scalars(
        select(Assignment).where(
            Assignment.project_id == pid,
            Assignment.teacher_id == obj.id
            if payload.entity_type == "teacher"
            else Assignment.class_id == obj.id,
        )
    ).all()
    assignment_ids = {assignment.id for assignment in assignments}
    lessons = (
        db.scalars(
            select(Lesson).where(
                Lesson.project_id == pid,
                Lesson.assignment_id.in_(assignment_ids),
            )
        ).all()
        if assignment_ids
        else []
    )
    lessons_by_assignment = defaultdict(list)
    for lesson in lessons:
        lessons_by_assignment[lesson.assignment_id].append(lesson)

    for assignment in assignments:
        teacher = db.get(Teacher, assignment.teacher_id)
        school_class = db.get(SchoolClass, assignment.class_id)
        subject = db.get(Subject, assignment.subject_id)
        if not teacher or not school_class or not subject:
            continue
        ensure_assignment_hard_feasible(
            p,
            teacher,
            school_class,
            subject,
            assignment.periods_per_week,
            assignment.block_mode,
            teacher_unavailable_slots=slots
            if payload.entity_type == "teacher"
            else None,
            class_unavailable_slots=(slots | class_grade_blocked_slots(school_class))
            if payload.entity_type == "class"
            else None,
        )

    fixed_rows = (
        db.scalars(
            select(FixedLesson).where(
                FixedLesson.project_id == pid,
                FixedLesson.assignment_id.in_(assignment_ids),
            )
        ).all()
        if assignment_ids
        else []
    )
    assignment_by_id = {assignment.id: assignment for assignment in assignments}
    for row in fixed_rows:
        assignment = assignment_by_id.get(row.assignment_id)
        if not assignment:
            continue
        size = fixed_row_size(
            p, assignment, row, lessons_by_assignment[row.assignment_id]
        )
        if size < 1:
            return JSONResponse(
                {
                    "ok": False,
                    "message": "Có dữ liệu tiết cố định cũ không xác định được kích thước cụm. Hãy bỏ ghim đó rồi lưu ràng buộc lại.",
                },
                409,
            )
        if slots.intersection(range(row.slot, row.slot + size)):
            return JSONResponse(
                {
                    "ok": False,
                    "message": "Ràng buộc mới xung đột với tiết cố định. Hãy bỏ cố định trước.",
                },
                409,
            )

    removed_ids = set()
    fixed_coverage = fixed_coverage_slots(db, p)
    for assignment in assignments:
        assignment_lessons = lessons_by_assignment[assignment.id]
        if assignment_requires_double(assignment):
            state = required_double_block_state(p, assignment, assignment_lessons)
            if not state["valid"]:
                return JSONResponse(
                    {
                        "ok": False,
                        "message": "Cấu trúc block tiết đôi hiện tại không toàn vẹn. Hãy sửa hoặc tạo lại lịch trước khi đổi ràng buộc.",
                    },
                    409,
                )
        if not assignment_requires_double(assignment):
            affected = [lesson for lesson in assignment_lessons if lesson.slot in slots]
            if any(lesson.locked for lesson in affected):
                return JSONResponse(
                    {
                        "ok": False,
                        "message": "Ràng buộc mới xung đột với tiết cố định. Hãy bỏ cố định trước.",
                    },
                    409,
                )
            removed_ids.update(lesson.id for lesson in affected)
            continue
        seen_blocks = set()
        for lesson in assignment_lessons:
            block_key = lesson.block_id or f"legacy:{lesson.id}"
            if block_key in seen_blocks:
                continue
            seen_blocks.add(block_key)
            affected = lesson_block_members(assignment_lessons, lesson)
            block_slots = {row.slot for row in affected}
            if not slots.intersection(block_slots):
                continue
            if any(row.locked for row in affected) or block_slots.intersection(
                fixed_coverage.get(assignment.id, set())
            ):
                return JSONResponse(
                    {
                        "ok": False,
                        "message": "Ràng buộc mới xung đột với block có tiết cố định. Hãy bỏ cố định trước.",
                    },
                    409,
                )
            removed_ids.update(row.id for row in affected)

    ensure_pinned_assignments_feasible(
        db, p, assignments,
        teacher_unavailable={obj.id: slots} if payload.entity_type == "teacher" else None,
        class_unavailable={obj.id: slots | class_grade_blocked_slots(obj)} if payload.entity_type == "class" else None,
    )
    confirmation = displacement_confirmation(removed_ids, payload)
    if confirmation is not None:
        return confirmation

    if payload.entity_type == "class":
        ensure_class_load_fits(
            p,
            obj,
            class_assigned_periods(db, pid, obj.id),
            unavailable_slots=slots | class_grade_blocked_slots(obj),
        )
    obj.unavailable_json = json.dumps(sorted(slots))
    for lesson in lessons:
        if lesson.id in removed_ids:
            db.delete(lesson)
    db.commit()
    return {"ok": True, "removed": len(removed_ids)}


@router.post("/api/projects/{pid}/session-locks")
def save_session_locks(
    pid: int,
    payload: SessionLocksIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    grade = db.get(Grade, payload.grade_id)
    if not grade or grade.project_id != pid:
        raise HTTPException(404, "Không tìm thấy khối lớp")
    maximum = project.days * project.sessions
    try:
        session_keys = normalize_slot_values(payload.sessions, maximum, strict=True)
    except ValueError as exc:
        message = str(exc).replace("tiết", "buổi")
        raise HTTPException(400, message) from exc
    blocked = []
    ppd = project.sessions * project.periods_per_session
    for key in session_keys:
        day = key // project.sessions
        session = key % project.sessions
        start = day * ppd + session * project.periods_per_session
        blocked.extend(range(start, start + project.periods_per_session))
    blocked = valid_slots(project, [*blocked, *payload.slots])
    classes = db.scalars(select(SchoolClass).where(
        SchoolClass.project_id == pid, SchoolClass.grade_id == grade.id
    )).all()
    class_ids = {row.id for row in classes}
    assignments = db.scalars(select(Assignment).where(Assignment.project_id == pid)).all()
    assignments = [row for row in assignments if row.class_id in class_ids]
    assignment_ids = {row.id for row in assignments}
    all_lessons = db.scalars(
        select(Lesson).where(Lesson.project_id == pid)
    ).all()
    all_lessons = [row for row in all_lessons if row.assignment_id in assignment_ids]
    lessons_by_assignment = defaultdict(list)
    for lesson in all_lessons:
        lessons_by_assignment[lesson.assignment_id].append(lesson)
    fixed_rows = db.scalars(
        select(FixedLesson).where(FixedLesson.project_id == pid)
    ).all()
    fixed_rows = [row for row in fixed_rows if row.assignment_id in assignment_ids]
    blocked_set = set(blocked)
    total = db.scalar(select(func.coalesce(func.sum(GradeSubjectRequirement.periods_per_week), 0)).where(
        GradeSubjectRequirement.project_id == pid, GradeSubjectRequirement.grade_id == grade.id,
    )) or 0
    ensure_grade_program_fits(project, grade, int(total), grade_blocked_slots=blocked_set)
    removed_ids = set()
    fixed_coverage = fixed_coverage_slots(db, project)

    # Khóa buổi phải tuân cùng quy tắc với ràng buộc giáo viên/lớp:
    # không âm thầm xóa các cụm đã được cố định.
    for row in fixed_rows:
        assignment = db.get(Assignment, row.assignment_id)
        if not assignment:
            continue
        lessons = lessons_by_assignment.get(row.assignment_id, [])
        size = fixed_row_size(project, assignment, row, lessons)
        if size < 1:
            return JSONResponse(
                {
                    "ok": False,
                    "message": "Có dữ liệu tiết cố định cũ không xác định được kích thước cụm. Hãy bỏ ghim đó trước khi đổi khóa buổi/tiết.",
                },
                409,
            )
        row_slots = set(range(row.slot, row.slot + size))
        if blocked_set.intersection(row_slots):
            return JSONResponse(
                {
                    "ok": False,
                    "message": "Buổi hoặc tiết mới khóa đang chứa tiết cố định. Hãy bỏ cố định trước.",
                },
                409,
            )
    if any(lesson.locked and lesson.slot in blocked_set for lesson in all_lessons):
        return JSONResponse(
            {
                "ok": False,
                "message": "Buổi hoặc tiết mới khóa đang chứa tiết cố định. Hãy bỏ cố định trước.",
            },
            409,
        )

    teachers = db.scalars(select(Teacher).where(Teacher.project_id == pid)).all()
    for school_class in classes:
        assigned = class_assigned_periods(db, pid, school_class.id)
        if assigned:
            ensure_class_load_fits(
                project,
                school_class,
                assigned,
                unavailable_slots=blocked_set | parse_slots(school_class.unavailable_json),
            )

    teacher_map = {teacher.id: teacher for teacher in teachers}
    class_map = {school_class.id: school_class for school_class in classes}
    for assignment in assignments:
        teacher = teacher_map.get(assignment.teacher_id)
        school_class = class_map.get(assignment.class_id)
        subject = db.get(Subject, assignment.subject_id)
        if teacher and school_class and subject:
            ensure_assignment_hard_feasible(
                project,
                teacher,
                school_class,
                subject,
                assignment.periods_per_week,
                assignment.block_mode,
                class_unavailable_slots=blocked_set | parse_slots(school_class.unavailable_json),
            )

    for assignment_id, lessons in lessons_by_assignment.items():
        if not any(lesson.slot in blocked_set for lesson in lessons):
            continue
        assignment = db.get(Assignment, assignment_id)
        if not assignment:
            for lesson in lessons:
                if lesson.slot in blocked_set:
                    removed_ids.add(lesson.id)
            continue
        if not assignment_requires_double(assignment):
            removed_ids.update(
                lesson.id for lesson in lessons if lesson.slot in blocked_set
            )
            continue
        state = required_double_block_state(project, assignment, lessons)
        if not state["valid"]:
            return JSONResponse(
                {
                    "ok": False,
                    "message": "Cấu trúc block tiết đôi hiện tại không toàn vẹn. Hãy sửa hoặc tạo lại lịch trước khi khóa buổi/tiết.",
                },
                409,
            )
        seen_blocks = set()
        for lesson in lessons:
            block_key = lesson.block_id or f"legacy:{lesson.id}"
            if block_key in seen_blocks:
                continue
            seen_blocks.add(block_key)
            affected = lesson_block_members(lessons, lesson)
            block_slots = {row.slot for row in affected}
            if not blocked_set.intersection(block_slots):
                continue
            if any(row.locked for row in affected) or block_slots.intersection(
                fixed_coverage.get(assignment_id, set())
            ):
                return JSONResponse(
                    {
                        "ok": False,
                        "message": "Buổi hoặc tiết mới khóa làm ảnh hưởng block có tiết cố định. Hãy bỏ cố định trước.",
                    },
                    409,
                )
            removed_ids.update(row.id for row in affected)
    ensure_pinned_assignments_feasible(
        db, project, assignments,
        class_unavailable={row.id: blocked_set | parse_slots(row.unavailable_json) for row in classes},
    )
    confirmation = displacement_confirmation(removed_ids, payload)
    if confirmation is not None:
        return confirmation

    grade.blocked_slots_json = json.dumps(blocked)
    for lesson in all_lessons:
        if lesson.id in removed_ids:
            db.delete(lesson)
    db.commit()
    return {
        "ok": True,
        "grade_id": payload.grade_id,
        "sessions": session_keys,
        "removed": len(removed_ids),
    }
