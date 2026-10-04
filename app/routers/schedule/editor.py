from __future__ import annotations

from fastapi import APIRouter
from app.services.runtime import *

router = APIRouter()


@router.post("/api/projects/{pid}/placement-options")
def placement_options(
    pid: int,
    payload: PlacementOptionsIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project(pid, user, db)
    has_assignment = payload.assignment_id is not None
    has_lesson = payload.lesson_id is not None
    if has_assignment == has_lesson:
        raise HTTPException(400, "Hãy chọn đúng một phân công hoặc một tiết đang xếp")

    if has_assignment:
        assignment = db.get(Assignment, payload.assignment_id)
        if not assignment or assignment.project_id != pid:
            raise HTTPException(404, "Phân công không còn tồn tại")
        current_lessons = db.scalars(
            select(Lesson).where(
                Lesson.project_id == pid, Lesson.assignment_id == assignment.id
            )
        ).all()
        current_slots = [row.slot for row in current_lessons]
        group_size = 1
        if assignment_requires_double(assignment):
            group_size = next_required_double_block_size(
                project, assignment, current_lessons
            )
            if group_size is None:
                return {
                    "ok": True,
                    "valid_slots": [],
                    "move_scope": "new",
                    "group_size": 0,
                    "message": "Cấu trúc block hiện tại không hợp lệ. Hãy tạo lại thời khóa biểu.",
                }
        if len(current_slots) >= int(assignment.periods_per_week) or group_size == 0:
            return {
                "ok": True,
                "valid_slots": [],
                "move_scope": "new",
                "group_size": group_size,
                "message": "Phân công này đã đủ số tiết/tuần.",
            }
        feasibility = assignment_feasibility_context(db, project, assignment)
        valid = []
        for slot in all_slots(project):
            if (
                slot % project.periods_per_session + group_size
                > project.periods_per_session
            ):
                continue
            target_slots = list(range(slot, slot + group_size))
            proposed = [*current_slots, *target_slots]
            if assignment_completion_feasible(
                db, project, assignment, proposed, context=feasibility
            ):
                valid.append(slot)
        return {
            "ok": True,
            "valid_slots": valid,
            "move_scope": "new",
            "group_size": group_size,
            "message": (
                f"Block {group_size} tiết sẽ được đặt cùng nhau; chỉ các vị trí hợp lệ được đánh dấu."
                if group_size > 1
                else "Chỉ các ô được đánh dấu mới có thể hoàn thành lịch hợp lệ."
            ),
        }

    lesson = db.get(Lesson, payload.lesson_id)
    if not lesson or lesson.project_id != pid:
        raise HTTPException(404, "Tiết học không còn tồn tại")
    assignment = db.get(Assignment, lesson.assignment_id)
    if not assignment or assignment.project_id != pid:
        raise HTTPException(409, "Phân công của tiết học không còn tồn tại")

    scope = str(payload.move_scope or "single").strip().lower()
    if scope not in {"single", "group"}:
        raise HTTPException(400, "Kiểu di chuyển không hợp lệ")
    if assignment_requires_double(assignment):
        # required_double is a hard constraint: a scheduled lesson moves with
        # its persisted block_id only. Never infer the block from adjacency.
        scope = "group"
    else:
        scope = "single"

    lessons = db.scalars(
        select(Lesson).where(
            Lesson.project_id == pid, Lesson.assignment_id == assignment.id
        )
    ).all()
    if assignment_requires_double(assignment):
        block_state = required_double_block_state(project, assignment, lessons)
        if not block_state["valid"]:
            return {
                "ok": True,
                "valid_slots": [],
                "move_scope": "group",
                "group_size": int(getattr(lesson, "block_size", 1) or 1),
                "message": "Block đang chọn không toàn vẹn. Hãy gỡ block hoặc tạo lại thời khóa biểu.",
            }
    if scope == "group":
        moving = lesson_block_members(lessons, lesson)
    else:
        moving = [lesson]

    fixed_slots = fixed_coverage_slots(db, project).get(assignment.id, set())
    if any(item.locked or item.slot in fixed_slots for item in moving):
        return {
            "ok": True,
            "valid_slots": [],
            "move_scope": scope,
            "group_size": len(moving),
            "message": (
                "Tiết đang chọn đã được cố định. Hãy bỏ cố định trước khi chuyển."
                if scope == "single"
                else "Cụm có tiết cố định. Hãy bỏ cố định cả cụm trước khi chuyển."
            ),
        }

    moving_ids = {item.id for item in moving}
    base_slots = [item.slot for item in lessons if item.id not in moving_ids]
    original_slots = {item.slot for item in moving}
    feasibility = assignment_feasibility_context(db, project, assignment)
    valid = []
    for start in all_slots(project):
        if (
            start % project.periods_per_session + len(moving)
            > project.periods_per_session
        ):
            continue
        target_slots = list(range(start, start + len(moving)))
        if set(target_slots) == original_slots:
            continue
        proposed = [*base_slots, *target_slots]
        if assignment_completion_feasible(
            db,
            project,
            assignment,
            proposed,
            enforce_pattern=True,
            context=feasibility,
        ):
            valid.append(start)

    return {
        "ok": True,
        "valid_slots": valid,
        "move_scope": scope,
        "group_size": len(moving),
        "pattern_relaxed": False,
        "message": (
            "Bắt buộc tiết đôi: cả cụm sẽ được di chuyển cùng nhau; "
            "chỉ các ô được đánh dấu mới thỏa toàn bộ ràng buộc hiện tại."
            if assignment_requires_double(assignment)
            else "Chỉ các ô được đánh dấu mới thỏa toàn bộ ràng buộc hiện tại."
        ),
    }


@router.post("/api/projects/{pid}/move")
def move(
    pid: int,
    payload: MoveIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    lesson = db.get(Lesson, payload.lesson_id)
    if not lesson or lesson.project_id != pid:
        raise HTTPException(404)
    assignment = db.get(Assignment, lesson.assignment_id)
    if not assignment or assignment.project_id != pid:
        raise HTTPException(409, "Phân công của tiết học không còn tồn tại")
    lessons = db.scalars(
        select(Lesson).where(
            Lesson.project_id == pid, Lesson.assignment_id == assignment.id
        )
    ).all()
    if assignment_requires_double(assignment):
        block_state = required_double_block_state(project, assignment, lessons)
        if not block_state["valid"]:
            raise HTTPException(
                409,
                "Cấu trúc block bắt buộc tiết đôi không toàn vẹn. Hãy gỡ block lỗi hoặc tạo lại thời khóa biểu.",
            )

    scope = str(payload.move_scope or "group").strip().lower()
    if scope not in {"single", "group"}:
        raise HTTPException(400, "Kiểu di chuyển không hợp lệ")
    if assignment_requires_double(assignment):
        if scope != "group":
            raise HTTPException(
                409,
                "Phân công bắt buộc tiết đôi chỉ được di chuyển cả cụm.",
            )
        scope = "group"
    else:
        scope = "single"

    if scope == "group":
        moving = lesson_block_members(lessons, lesson)
        group_slots = {item.slot for item in moving}
    else:
        group_slots = {lesson.slot}
        moving = [lesson]

    fixed_slots = fixed_coverage_slots(db, project).get(assignment.id, set())
    if any(item.locked or item.slot in fixed_slots for item in moving):
        raise HTTPException(
            409,
            "Tiết đang chọn đã được cố định. Hãy bỏ cố định trước khi chuyển."
            if scope == "single"
            else "Cụm có tiết cố định. Hãy bỏ cố định cả cụm trước khi chuyển.",
        )

    start = payload.slot
    if start not in all_slots(project):
        raise HTTPException(400, "Ô thời khóa biểu không hợp lệ")
    if start % project.periods_per_session + len(moving) > project.periods_per_session:
        raise HTTPException(409, "Cụm tiết vượt quá cuối buổi học")
    target_slots = list(range(start, start + len(moving)))
    moving_ids = {item.id for item in moving}
    proposed = [
        item.slot for item in lessons if item.id not in moving_ids
    ] + target_slots
    if not assignment_completion_feasible(
        db, project, assignment, proposed, enforce_pattern=True
    ):
        raise HTTPException(
            409,
            "Không thể chuyển tiết tới đây vì trùng lịch, tiết tránh hoặc giới hạn xếp tiết."
            if scope == "single"
            else "Không thể chuyển cả cụm tới đây vì trùng lịch, tiết tránh hoặc giới hạn xếp tiết.",
        )
    if group_slots == set(target_slots):
        return {
            "ok": True,
            "moved": 0,
            "removed_ids": [],
            "moved_lessons": [],
            "move_scope": scope,
            "schedule_validation": schedule_ui_validation_report(db, project),
        }

    # Delete/flush before inserting prevents UNIQUE collisions when the new
    # range partly overlaps its old range. Everything stays in one transaction.
    for item in moving:
        db.delete(item)
    db.flush()
    created = []
    block_id = lesson.block_id or new_schedule_block_id()
    block_size = int(getattr(lesson, "block_size", len(moving)) or len(moving))
    for slot in target_slots:
        item = Lesson(
            project_id=pid,
            assignment_id=assignment.id,
            slot=slot,
            block_id=block_id,
            block_size=block_size,
            locked=False,
        )
        db.add(item)
        created.append(item)
    db.commit()
    return {
        "ok": True,
        "moved": len(created),
        "removed_ids": sorted(moving_ids),
        "moved_lessons": [
            {
                "id": item.id,
                "assignment_id": item.assignment_id,
                "slot": item.slot,
                "block_id": item.block_id,
                "block_size": item.block_size,
                "locked": item.locked,
            }
            for item in created
        ],
        "move_scope": scope,
        "schedule_validation": schedule_ui_validation_report(db, project),
    }


@router.post("/api/projects/{pid}/lessons")
def add_manual_lesson(
    pid: int,
    payload: ManualLessonIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    assignment = db.get(Assignment, payload.assignment_id)
    if not assignment or assignment.project_id != pid:
        raise HTTPException(404)
    current_lessons = db.scalars(
        select(Lesson).where(
            Lesson.project_id == pid, Lesson.assignment_id == assignment.id
        )
    ).all()
    if len(current_lessons) >= assignment.periods_per_week:
        return JSONResponse(
            {"ok": False, "message": "Phân công này đã đủ số tiết/tuần."}, 409
        )
    group_size = 1
    if assignment_requires_double(assignment):
        group_size = next_required_double_block_size(
            project, assignment, current_lessons
        )
        if group_size is None:
            return JSONResponse(
                {
                    "ok": False,
                    "message": "Cấu trúc block hiện tại không hợp lệ. Hãy tạo lại thời khóa biểu.",
                },
                409,
            )
    if (
        payload.slot % project.periods_per_session + group_size
        > project.periods_per_session
    ):
        return JSONResponse(
            {"ok": False, "message": "Block tiết vượt quá cuối buổi học."}, 409
        )
    target_slots = list(range(payload.slot, payload.slot + group_size))
    for slot in target_slots:
        error = lesson_slot_error(db, project, assignment, slot)
        if error:
            return JSONResponse({"ok": False, "message": error}, 409)
    current_slots = [row.slot for row in current_lessons]
    if not assignment_completion_feasible(
        db, project, assignment, [*current_slots, *target_slots]
    ):
        return JSONResponse(
            {
                "ok": False,
                "message": f"Vị trí này không thể hoàn thành hợp lệ theo chế độ {assignment_pattern_label(assignment)} và các ràng buộc hiện tại.",
            },
            409,
        )
    block_id = new_schedule_block_id()
    created = []
    for slot in target_slots:
        row = Lesson(
            project_id=pid,
            assignment_id=assignment.id,
            slot=slot,
            block_id=block_id,
            block_size=group_size,
            locked=False,
        )
        db.add(row)
        created.append(row)
    db.commit()
    return {
        "ok": True,
        "id": created[0].id,
        "added_lessons": [
            {
                "id": row.id,
                "assignment_id": row.assignment_id,
                "slot": row.slot,
                "block_id": row.block_id,
                "block_size": row.block_size,
                "locked": row.locked,
            }
            for row in created
        ],
        "schedule_validation": schedule_ui_validation_report(db, project),
    }


@router.delete("/api/projects/{pid}/lessons/{lesson_id}")
def remove_manual_lesson(
    pid: int,
    lesson_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    lesson = db.get(Lesson, lesson_id)
    if not lesson or lesson.project_id != pid:
        raise HTTPException(404)
    fixed_slots = fixed_coverage_slots(db, project).get(lesson.assignment_id, set())
    if lesson.locked or lesson.slot in fixed_slots:
        return JSONResponse({"ok": False, "message": "Tiết cố định không thể gỡ."}, 409)
    assignment = db.get(Assignment, lesson.assignment_id)
    if not assignment or assignment.project_id != pid:
        return JSONResponse(
            {"ok": False, "message": "Phân công của tiết học không còn tồn tại."}, 409
        )

    lessons = db.scalars(
        select(Lesson).where(Lesson.assignment_id == assignment.id)
    ).all()
    group = (
        lesson_block_members(lessons, lesson)
        if assignment_requires_double(assignment)
        else [lesson]
    )
    if any(item.locked or item.slot in fixed_slots for item in group):
        return JSONResponse(
            {"ok": False, "message": "Block có tiết cố định nên không thể gỡ."}, 409
        )
    remove_ids = {item.id for item in group}

    for item in lessons:
        if item.id in remove_ids:
            db.delete(item)
    db.commit()
    removed = len(remove_ids)
    message = (
        "Đã trả tiết về kho."
        if removed == 1
        else f"Đã trả cả cụm {removed} tiết về kho."
    )
    return {"ok": True, "removed": removed, "message": message}


@router.delete("/api/projects/{pid}/assignments/{assignment_id}/lessons")
def return_assignment_to_tray(
    pid: int,
    assignment_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    assignment = db.get(Assignment, assignment_id)
    if not assignment or assignment.project_id != pid:
        raise HTTPException(404)
    lessons = db.scalars(
        select(Lesson).where(
            Lesson.project_id == pid, Lesson.assignment_id == assignment_id
        )
    ).all()

    # Lesson.locked is normally the source of truth, but old/imported projects can
    # temporarily have FixedLesson metadata whose matching Lesson has not yet had
    # locked=True restored. Treat both representations as locked so the first step
    # never removes a fixed lesson and the response reports how many fixed lessons
    # were intentionally kept on the timetable.
    fixed_slots = fixed_coverage_slots(db, project).get(assignment_id, set())
    protected_ids = {
        lesson.id for lesson in lessons if lesson.locked or lesson.slot in fixed_slots
    }
    if assignment_requires_double(assignment):
        for lesson in lessons:
            members = lesson_block_members(lessons, lesson)
            if any(member.id in protected_ids for member in members):
                protected_ids.update(member.id for member in members)
    locked_lessons = [lesson for lesson in lessons if lesson.id in protected_ids]
    removable = [lesson for lesson in lessons if lesson.id not in protected_ids]

    for lesson in removable:
        db.delete(lesson)
    db.commit()
    locked = len(locked_lessons)
    message = f"Đã đưa {len(removable)} tiết chưa cố định về khay."
    if locked:
        message += f" Giữ nguyên {locked} tiết đã cố định."
    return {"ok": True, "removed": len(removable), "locked": locked, "message": message}


@router.delete("/api/projects/{pid}/lessons")
def return_all_to_tray(
    pid: int, user: User = Depends(current_user), db: Session = Depends(db_session)
):
    project = get_project_for_update(pid, user, db)
    lessons = db.scalars(select(Lesson).where(Lesson.project_id == pid)).all()
    fixed_slots = fixed_coverage_slots(db, project)
    assignments = {
        row.id: row
        for row in db.scalars(
            select(Assignment).where(Assignment.project_id == pid)
        ).all()
    }
    lessons_by_assignment = defaultdict(list)
    for lesson in lessons:
        lessons_by_assignment[lesson.assignment_id].append(lesson)
    protected_ids = {
        lesson.id
        for lesson in lessons
        if lesson.locked or lesson.slot in fixed_slots.get(lesson.assignment_id, set())
    }
    for assignment_id, assignment_lessons in lessons_by_assignment.items():
        assignment = assignments.get(assignment_id)
        if not assignment or not assignment_requires_double(assignment):
            continue
        for lesson in assignment_lessons:
            members = lesson_block_members(assignment_lessons, lesson)
            if any(member.id in protected_ids for member in members):
                protected_ids.update(member.id for member in members)
    removable = [lesson for lesson in lessons if lesson.id not in protected_ids]
    removable_ids = {lesson.id for lesson in removable}
    fixed_count = sum(1 for lesson in lessons if lesson.id not in removable_ids)
    for lesson in removable:
        db.delete(lesson)
    db.commit()
    message = f"Đã đưa {len(removable)} tiết chưa cố định về khay."
    if fixed_count:
        message += f" Giữ nguyên {fixed_count} tiết đã cố định."
    return {
        "ok": True,
        "removed": len(removable),
        "locked": fixed_count,
        "message": message,
    }
