from __future__ import annotations

from fastapi import APIRouter
from app.services.runtime import *

router = APIRouter()

@router.post("/api/projects/{pid}/fixed")
def fixed(
    pid: int,
    payload: FixedIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    p = get_project_for_update(pid, user, db)
    assignment = db.get(Assignment, payload.assignment_id)
    if not assignment or assignment.project_id != pid:
        raise HTTPException(404)
    lessons = db.scalars(select(Lesson).where(
        Lesson.project_id == pid, Lesson.assignment_id == assignment.id
    )).all()
    slots = {lesson.slot for lesson in lessons}
    if payload.slot not in slots:
        raise HTTPException(400, "Hãy chọn một tiết đang có trên lịch để cố định")
    selected_lesson = next((row for row in lessons if row.slot == payload.slot), None)
    members = (
        lesson_block_members(lessons, selected_lesson)
        if assignment_requires_double(assignment) and selected_lesson else [selected_lesson]
    )
    run_slots = {row.slot for row in members if row is not None}
    for lesson in lessons:
        if lesson.slot in run_slots:
            error = lesson_slot_error(db, p, assignment, lesson.slot, lesson.id)
            if error:
                raise HTTPException(409, error)
    # One user action pins exactly the persisted scheduling block. Required
    # double periods therefore lock atomically; neighboring blocks are untouched.
    coverage = fixed_coverage_slots(db, p).get(assignment.id, set())
    if not coverage.issubset(slots):
        raise HTTPException(409, "Có cụm cố định đang thiếu tiết. Hãy xếp bổ sung hoặc bỏ ghim đó trước khi cố định thêm.")
    for lesson in lessons:
        if lesson.slot in run_slots or lesson.slot in coverage:
            lesson.locked = True
    error = normalize_assignment_fixed_rows(db, p, assignment, lessons)
    if error:
        db.rollback()
        raise HTTPException(409, error)
    db.flush()
    if not assignment_completion_feasible(db, p, assignment, slots):
        db.rollback()
        raise HTTPException(409, "Lịch hiện tại không thể hoàn thành hợp lệ. Hãy điều chỉnh trước khi ghim.")
    db.commit()
    return {"ok": True, "pinned": len(run_slots),
            "message": f"Đã cố định cả cụm {len(run_slots)} tiết." if len(run_slots) > 1 else "Đã cố định tiết đang chọn."}

@router.delete("/api/projects/{pid}/fixed/{assignment_id}/{slot}")
def remove_fixed_group(
    pid: int,
    assignment_id: int,
    slot: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    p = get_project_for_update(pid, user, db)
    assignment = db.get(Assignment, assignment_id)
    if not assignment or assignment.project_id != pid:
        raise HTTPException(404)
    lessons = db.scalars(
        select(Lesson).where(
            Lesson.project_id == pid, Lesson.assignment_id == assignment_id
        )
    ).all()
    rows = db.scalars(
        select(FixedLesson).where(
            FixedLesson.project_id == pid, FixedLesson.assignment_id == assignment_id
        )
    ).all()
    selected_lesson = next((row for row in lessons if row.slot == slot), None)
    members = (
        lesson_block_members(lessons, selected_lesson)
        if assignment_requires_double(assignment) and selected_lesson else [selected_lesson]
    )
    run_slots = {row.slot for row in members if row is not None} or {slot}
    targets = []
    for row in rows:
        size = max(1, fixed_row_size(p, assignment, row, lessons))
        if run_slots.intersection(range(row.slot, row.slot + size)):
            targets.append((row, size))
    if not targets and not any(item.locked and item.slot in run_slots for item in lessons):
        raise HTTPException(404, "Không tìm thấy cụm tiết cố định")
    unlocked = set(run_slots)
    for row, size in targets:
        unlocked.update(range(row.slot, row.slot + size))
        db.delete(row)
    remaining = []
    for row in rows:
        if all(row.id != target.id for target, _size in targets):
            size = fixed_row_size(p, assignment, row, lessons)
            if size < 1:
                continue
            remaining.extend(range(row.slot, row.slot + size))
    for lesson in lessons:
        if lesson.slot in unlocked and lesson.slot not in remaining:
            lesson.locked = False
    db.commit()
    released_count = len(unlocked - set(remaining))
    return {
        "ok": True,
        "message": (
            f"Đã bỏ cố định cả block {released_count} tiết."
            if released_count > 1
            else "Đã bỏ cố định tiết đang chọn."
        ),
    }

@router.delete("/api/projects/{pid}/fixed/{assignment_id}")
def remove_fixed(
    pid: int,
    assignment_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    get_project_for_update(pid, user, db)
    assignment = db.get(Assignment, assignment_id)
    if not assignment or assignment.project_id != pid:
        raise HTTPException(404)
    fixed_rows = db.scalars(
        select(FixedLesson).where(
            FixedLesson.project_id == pid, FixedLesson.assignment_id == assignment_id
        )
    ).all()
    for row in fixed_rows:
        db.delete(row)
    lessons = db.scalars(
        select(Lesson).where(
            Lesson.project_id == pid, Lesson.assignment_id == assignment_id
        )
    ).all()
    for lesson in lessons:
        lesson.locked = False
    db.commit()
    return {"ok": True, "message": "Đã bỏ toàn bộ cố định của phân công."}

@router.post("/api/projects/{pid}/generate")
def generate(
    pid: int,
    payload: Optional[GenerateScheduleIn] = None,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    p = get_project_for_update(pid, user, db)
    assignments = db.scalars(
        select(Assignment).where(Assignment.project_id == pid)
    ).all()
    classes = db.scalars(
        select(SchoolClass).where(SchoolClass.project_id == pid)
    ).all()
    input_validation = schedule_input_validation_report(
        db, p, assignments=assignments, classes=classes
    )
    reference_issues = input_validation["assignment_reference_issues"]
    if reference_issues:
        labels = {"teacher_id": "giáo viên", "class_id": "lớp", "subject_id": "môn"}
        details = []
        for issue in reference_issues[:5]:
            refs = ", ".join(
                f"{labels.get(ref['field'], ref['field'])} #{ref['id']}"
                for ref in issue["invalid_refs"]
            )
            details.append(f"phân công #{issue['assignment_id']}: {refs}")
        suffix = (
            f"; và {len(reference_issues) - 5} phân công khác"
            if len(reference_issues) > 5
            else ""
        )
        return JSONResponse(
            {
                "ok": False,
                "reason": "assignment_project_mismatch",
                "assignment_reference_issues": reference_issues,
                "message": (
                    "Không thể xếp lịch vì có phân công tham chiếu giáo viên, lớp hoặc môn "
                    "không còn tồn tại hoặc thuộc project khác: "
                    + "; ".join(details)
                    + suffix
                    + ". Hãy sửa/xóa phân công lỗi trước khi xếp lại."
                ),
            },
            409,
        )
    duplicate_issues = input_validation["duplicate_assignment_issues"]
    teacher_subject_issues = input_validation["teacher_subject_issues"]
    if teacher_subject_issues:
        details = "; ".join(
            f"{item['teacher_name']} – {item['subject_name']} (phân công #{item['assignment_id']})"
            for item in teacher_subject_issues[:5]
        )
        suffix = (
            f"; và {len(teacher_subject_issues) - 5} phân công khác"
            if len(teacher_subject_issues) > 5
            else ""
        )
        return JSONResponse(
            {
                "ok": False,
                "reason": "teacher_subject_mismatch",
                "teacher_subject_issues": teacher_subject_issues,
                "message": (
                    "Không thể xếp lịch vì có giáo viên được phân công môn chưa được cấu hình chuyên môn: "
                    f"{details}{suffix}. Hãy sửa chuyên môn hoặc chuyển phân công trước khi xếp lại."
                ),
            },
            409,
        )
    if duplicate_issues:
        details = "; ".join(
            f"{item['class_name']} – {item['subject_name']} "
            f"(phân công ID {', '.join(map(str, item['assignment_ids']))})"
            for item in duplicate_issues[:5]
        )
        suffix = (
            f"; và {len(duplicate_issues) - 5} cặp khác"
            if len(duplicate_issues) > 5
            else ""
        )
        return JSONResponse(
            {
                "ok": False,
                "reason": "duplicate_assignments",
                "duplicate_assignment_issues": duplicate_issues,
                "message": (
                    "Không thể xếp lịch vì một lớp–môn đang có nhiều phân công: "
                    f"{details}{suffix}. Hãy xóa hoặc chuyển dữ liệu để mỗi lớp–môn "
                    "chỉ còn một giáo viên rồi xếp lại."
                ),
            },
            409,
        )
    curriculum_issues = input_validation["grade_requirement_issues"]
    if curriculum_issues:
        details = []
        for item in curriculum_issues[:5]:
            if item["issue_type"] == "missing":
                details.append(
                    f"{item['class_name']} – {item['subject_name']}: thiếu phân công "
                    f"{item['required_periods']} tiết/tuần"
                )
            elif item["issue_type"] == "extra":
                details.append(
                    f"{item['class_name']} – {item['subject_name']}: môn không thuộc chương trình khối"
                )
            else:
                mode_labels = {
                    "free": "Tự do",
                    "preferred_double": "Ưu tiên tiết đôi",
                    "required_double": "Bắt buộc tiết đôi",
                }
                current_mode = mode_labels.get(
                    item["assigned_mode"], item["assigned_mode"]
                )
                required_mode = mode_labels.get(
                    item["required_mode"], item["required_mode"]
                )
                details.append(
                    f"{item['class_name']} – {item['subject_name']}: đang {item['assigned_periods']} tiết/tuần · {current_mode}, "
                    f"chương trình khối yêu cầu {item['required_periods']} tiết/tuần · {required_mode}"
                )
        suffix = (
            f"; và {len(curriculum_issues) - 5} mục khác"
            if len(curriculum_issues) > 5
            else ""
        )
        return JSONResponse(
            {
                "ok": False,
                "reason": "grade_requirements_mismatch",
                "grade_requirement_issues": curriculum_issues,
                "message": (
                    "Không thể xếp lịch vì phân công chưa khớp chương trình chuẩn theo khối: "
                    + "; ".join(details)
                    + suffix
                    + ". Hãy bổ sung, chỉnh hoặc xóa phân công dư trước khi xếp tự động."
                ),
            },
            409,
        )
    capacity_issues = input_validation["capacity_issues"]
    if capacity_issues:
        details = "; ".join(
            f"{item['teacher_name']}: đã phân công {item['assigned']} tiết, "
            f"tối đa xếp được {item['capacity']} tiết (dư {item['excess']})"
            for item in capacity_issues[:5]
        )
        suffix = (
            f"; và {len(capacity_issues) - 5} giáo viên khác"
            if len(capacity_issues) > 5
            else ""
        )
        return JSONResponse(
            {
                "ok": False,
                "reason": "teacher_over_capacity",
                "capacity_issues": capacity_issues,
                "message": (
                    "Không thể xếp đầy đủ vì tải dạy vượt số ô khả dụng: "
                    f"{details}{suffix}. Hãy giảm/chuyển phân công, tăng giới hạn "
                    "tiết/ngày hoặc bỏ bớt tiết tránh rồi xếp lại."
                ),
            },
            409,
        )
    class_capacity_issues = input_validation["class_capacity_issues"]
    if class_capacity_issues:
        details = "; ".join(
            f"{item['class_name']}: cần {item['assigned']} tiết, "
            f"chỉ còn {item['capacity']} ô (dư {item['excess']})"
            for item in class_capacity_issues[:5]
        )
        suffix = (
            f"; và {len(class_capacity_issues) - 5} lớp khác"
            if len(class_capacity_issues) > 5
            else ""
        )
        return JSONResponse(
            {
                "ok": False,
                "reason": "class_over_capacity",
                "class_capacity_issues": class_capacity_issues,
                "message": (
                    "Không thể xếp đầy đủ vì tải học của lớp vượt số ô khả dụng: "
                    f"{details}{suffix}. Hãy giảm phân công hoặc bỏ bớt khóa/tiết tránh của lớp."
                ),
            },
            409,
        )
    fixed_definition_issues = input_validation["fixed_definition_issues"]
    if fixed_definition_issues:
        details = "; ".join(
            item.get("message", "Dữ liệu tiết cố định không hợp lệ")
            for item in fixed_definition_issues[:5]
        )
        suffix = (
            f"; và {len(fixed_definition_issues) - 5} lỗi ghim khác"
            if len(fixed_definition_issues) > 5
            else ""
        )
        return JSONResponse(
            {
                "ok": False,
                "reason": "fixed_lesson_invalid",
                "fixed_definition_issues": fixed_definition_issues,
                "message": (
                    "Không thể xếp lịch vì dữ liệu tiết cố định không hợp lệ: "
                    f"{details}{suffix} Hãy bỏ ghim lỗi rồi cố định lại."
                ),
            },
            409,
        )

    availability_issues = input_validation["assignment_availability_issues"]
    if availability_issues:
        details = "; ".join(item["message"] for item in availability_issues[:5])
        suffix = (
            f"; và {len(availability_issues) - 5} phân công khác"
            if len(availability_issues) > 5 else ""
        )
        return JSONResponse(
            {
                "ok": False,
                "reason": "assignment_availability_invalid",
                "assignment_availability_issues": availability_issues,
                "message": details + suffix,
            },
            409,
        )

    existing = db.scalars(select(Lesson).where(Lesson.project_id == pid)).all()
    assignment_by_id = {assignment.id: assignment for assignment in assignments}

    # Chuẩn hóa dữ liệu cố định cũ và hỗ trợ nhiều cụm cố định trên một phân công.
    lessons_by_assignment = defaultdict(list)
    for lesson in existing:
        lessons_by_assignment[lesson.assignment_id].append(lesson)
    fixed_rows = db.scalars(
        select(FixedLesson).where(FixedLesson.project_id == pid)
    ).all()
    fixed_changed = False
    assignments_with_unsatisfied_fixed = set()
    fixed_specs_by_assignment = defaultdict(list)
    for fixed_row in fixed_rows:
        assignment = assignment_by_id.get(fixed_row.assignment_id)
        if not assignment:
            db.delete(fixed_row)
            fixed_changed = True
            continue
        size = fixed_row_size(
            p, assignment, fixed_row, lessons_by_assignment[assignment.id]
        )
        if size < 1:
            return JSONResponse(
                {
                    "ok": False,
                    "message": (
                        "Có dữ liệu tiết cố định cũ không xác định được là tiết lẻ hay cặp tiết. "
                        "Hãy bỏ ghim tại ô đó rồi cố định lại trước khi xếp lịch."
                    ),
                },
                409,
            )
        fixed_specs_by_assignment[assignment.id].append((fixed_row.slot, size))
        if fixed_row.group_size != size:
            fixed_row.group_size = size
            fixed_changed = True
        expected_slots = set(range(fixed_row.slot, fixed_row.slot + size))
        matching = {
            lesson.slot: lesson
            for lesson in lessons_by_assignment[assignment.id]
            if lesson.slot in expected_slots
        }
        if expected_slots.issubset(matching):
            for slot in expected_slots:
                if not matching[slot].locked:
                    matching[slot].locked = True
                    fixed_changed = True
        else:
            assignments_with_unsatisfied_fixed.add(assignment.id)

    for assignment_id, fixed_specs in fixed_specs_by_assignment.items():
        assignment = assignment_by_id[assignment_id]
        fixed_error = fixed_group_validation_error(
            assignment_groups(assignment),
            fixed_specs,
            days=p.days,
            sessions=p.sessions,
            periods_per_session=p.periods_per_session,
        )
        if fixed_error:
            return JSONResponse(
                {
                    "ok": False,
                    "message": f"Dữ liệu tiết cố định của phân công không hợp lệ: {fixed_error} Hãy bỏ các ghim dư/trùng rồi xếp lại.",
                },
                409,
            )

    for assignment_id in assignments_with_unsatisfied_fixed:
        for lesson in lessons_by_assignment[assignment_id]:
            if not lesson.locked:
                db.delete(lesson)
                fixed_changed = True
    if fixed_changed:
        db.flush()
        existing = db.scalars(select(Lesson).where(Lesson.project_id == pid)).all()

    # Rà lại lịch cũ trước mỗi lần xếp vì các ràng buộc chính thức có thể đã
    # thay đổi sau khi lịch được tạo. Nguyện vọng giáo viên chỉ để tham khảo
    # và tuyệt đối không được đọc ở đây hoặc ở solver.
    invalid_lessons = []
    rebuild_assignment_ids = set()
    for lesson in minimal_schedule_invalid_lessons(db, p, assignments, existing):
        assignment = assignment_by_id.get(lesson.assignment_id)
        if not assignment:
            invalid_lessons.append(lesson)
            continue
        if lesson.locked:
            invalid_lessons.append(lesson)
        elif assignment_requires_double(assignment):
            rebuild_assignment_ids.add(assignment.id)
        else:
            invalid_lessons.append(lesson)

    existing_by_assignment = defaultdict(list)
    for lesson in existing:
        existing_by_assignment[lesson.assignment_id].append(lesson)
    for assignment in assignments:
        lessons_for_assignment = existing_by_assignment[assignment.id]
        if not lessons_for_assignment:
            continue
        if assignment_requires_double(assignment):
            block_state = required_double_block_state(p, assignment, lessons_for_assignment)
            if not block_state["valid"]:
                rebuild_assignment_ids.add(assignment.id)
        else:
            slots_for_assignment = [lesson.slot for lesson in lessons_for_assignment]
            if remaining_pattern_groups(p, assignment, slots_for_assignment) is None:
                rebuild_assignment_ids.add(assignment.id)

    if rebuild_assignment_ids:
        # Với required_double, lỗi ở một tiết di động chỉ yêu cầu dựng lại phần
        # di động của phân công. Các tiết khóa hợp lệ phải được giữ lại; chỉ khi
        # chính tập tiết khóa không thể thuộc bất kỳ mẫu hợp lệ nào mới báo lỗi
        # cố định.
        for assignment_id in rebuild_assignment_ids:
            assignment = assignment_by_id.get(assignment_id)
            assignment_lessons = [
                lesson for lesson in existing if lesson.assignment_id == assignment_id
            ]
            locked_assignment_lessons = [
                lesson for lesson in assignment_lessons if lesson.locked
            ]
            if assignment and locked_assignment_lessons:
                if assignment_requires_double(assignment):
                    locked_state = required_double_block_state(
                        p, assignment, locked_assignment_lessons
                    )
                    if not locked_state["valid"]:
                        invalid_lessons.extend(locked_assignment_lessons)
                else:
                    locked_slots = [lesson.slot for lesson in locked_assignment_lessons]
                    if remaining_pattern_groups(p, assignment, locked_slots) is None:
                        invalid_lessons.extend(locked_assignment_lessons)
            invalid_lessons.extend(
                lesson for lesson in assignment_lessons if not lesson.locked
            )
    invalid_lessons = list({lesson.id: lesson for lesson in invalid_lessons}.values())
    locked_invalid = [lesson for lesson in invalid_lessons if lesson.locked]
    if locked_invalid:
        return JSONResponse(
            {
                "ok": False,
                "message": f"Có {len(locked_invalid)} tiết cố định xung đột với ràng buộc hoặc chế độ xếp tiết mới. Hãy bỏ cố định hoặc điều chỉnh ràng buộc trước khi xếp lại.",
            },
            409,
        )
    for lesson in invalid_lessons:
        db.delete(lesson)
    if invalid_lessons:
        db.flush()
        existing = db.scalars(select(Lesson).where(Lesson.project_id == pid)).all()

    # Tính số tiết còn thiếu theo từng phân công, không lấy tổng toàn project.
    # Cách này vẫn đúng nếu dữ liệu cũ/import từng bị lệch giữa các phân công
    # (một phân công thừa tiết trong khi phân công khác lại thiếu).
    existing_counts = Counter(lesson.assignment_id for lesson in existing)
    excess_assignment_issues = []
    for assignment in assignments:
        existing_count = existing_counts[assignment.id]
        required_count = int(assignment.periods_per_week or 0)
        if existing_count <= required_count:
            continue
        school_class = db.get(SchoolClass, assignment.class_id)
        subject = db.get(Subject, assignment.subject_id)
        teacher = db.get(Teacher, assignment.teacher_id)
        excess_assignment_issues.append(
            {
                "assignment_id": assignment.id,
                "class_name": school_class.name
                if school_class
                else f"Lớp #{assignment.class_id}",
                "subject_name": subject.name
                if subject
                else f"Môn #{assignment.subject_id}",
                "teacher_name": teacher.name
                if teacher
                else f"GV #{assignment.teacher_id}",
                "required": required_count,
                "existing": existing_count,
                "excess": existing_count - required_count,
            }
        )
    if excess_assignment_issues:
        details = "; ".join(
            f"{item['class_name']} – {item['subject_name']} ({item['existing']}/{item['required']} tiết)"
            for item in excess_assignment_issues[:5]
        )
        suffix = (
            f"; và {len(excess_assignment_issues) - 5} phân công khác"
            if len(excess_assignment_issues) > 5
            else ""
        )
        return JSONResponse(
            {
                "ok": False,
                "reason": "excess_assignment_periods",
                "excess_assignment_issues": excess_assignment_issues,
                "message": (
                    "Không thể tiếp tục xếp lịch vì có phân công đang thừa số tiết/tuần: "
                    f"{details}{suffix}. Hãy đưa bớt tiết dư về khay rồi xếp lại."
                ),
            },
            409,
        )

    missing = sum(
        int(assignment.periods_per_week or 0) - existing_counts[assignment.id]
        for assignment in assignments
    )

    def finalize_generated_schedule(response_payload, *, invalid_status_code: int = 500):
        """Run the same authoritative integrity gate before committing."""
        db.flush()
        integrity = schedule_integrity_report(db, p)
        if not integrity["valid"]:
            logger.error(
                "Generated/current timetable failed final validation: %s",
                integrity,
            )
            db.rollback()
            return JSONResponse(
                {
                    "ok": False,
                    "reason": (
                        "schedule_integrity_failed"
                        if invalid_status_code < 500
                        else "solver_validation_failed"
                    ),
                    "message": (
                        "Thời khóa biểu hiện tại chưa vượt qua kiểm tra toàn vẹn. "
                        "Dữ liệu trước thao tác được giữ nguyên; hãy xử lý các lỗi được báo rồi thử lại."
                    ),
                    "integrity": integrity,
                },
                invalid_status_code,
            )

        db.commit()
        return response_payload

    # Từ lần xếp thứ hai trở đi, giữ nguyên lịch khi chỉ bổ sung phần thiếu.
    # Nếu người dùng đã xác nhận rebuild, đi thẳng vào rebuild thay vì chạy lại
    # solve_missing rồi mới rebuild lần thứ hai.
    if existing:
        if missing == 0:
            return finalize_generated_schedule(
                {
                    "ok": True,
                    "score": 0,
                    "unscheduled": 0,
                    "message": "Thời khóa biểu đã đủ tiết và vượt qua kiểm tra toàn vẹn.",
                },
                invalid_status_code=409,
            )

        if payload and payload.allow_rebuild:
            rebuild = solve_rebuild(db, p, tries=260)
            if rebuild["unscheduled"] > 0:
                if rebuild.get("proven_infeasible"):
                    message = (
                        "Các ràng buộc và tiết cố định hiện tại không cho phép "
                        "tạo một thời khóa biểu đầy đủ."
                    )
                else:
                    message = (
                        "Chưa tìm được lịch đầy đủ trong giới hạn tìm kiếm hiện tại; "
                        f"còn {rebuild['unscheduled']} tiết chưa xếp. "
                        "Dữ liệu lịch hiện tại chưa bị thay đổi."
                    )
                return JSONResponse(
                    {
                        "ok": False,
                        "score": rebuild["score"],
                        "unscheduled": rebuild["unscheduled"],
                        "message": message,
                    },
                    409,
                )

            current_lessons = db.scalars(
                select(Lesson).where(Lesson.project_id == pid)
            ).all()
            moved_count = sum(1 for lesson in current_lessons if not lesson.locked)
            for lesson in current_lessons:
                if not lesson.locked:
                    db.delete(lesson)
            db.flush()
            add_generated_lessons(db, p, rebuild["lessons"])
            return finalize_generated_schedule(
                {
                    "ok": True,
                    "score": rebuild["score"],
                    "unscheduled": 0,
                    "message": (
                        f"Đã giữ nguyên các tiết cố định và xếp lại {moved_count} tiết "
                        "không cố định để hoàn thành thời khóa biểu."
                    ),
                }
            )

        result = solve_missing(db, p, tries=160)
        if result["unscheduled"] > 0:
            # Không chạy solve_rebuild ở request này. Người dùng chưa cho phép
            # di chuyển lịch hiện có, nên chỉ xin xác nhận và để request sau đi
            # thẳng vào rebuild. Điều này loại bỏ một lần giải nặng bị lặp lại.
            current_lessons = db.scalars(
                select(Lesson).where(Lesson.project_id == pid)
            ).all()
            moved_count = sum(1 for lesson in current_lessons if not lesson.locked)
            return JSONResponse(
                {
                    "ok": False,
                    "requires_confirmation": True,
                    "moved_count": moved_count,
                    "score": result["score"],
                    "unscheduled": result["unscheduled"],
                    "message": (
                        "Không thể chỉ bổ sung phần còn thiếu mà giữ nguyên toàn bộ "
                        "lịch hiện tại. Hệ thống cần được phép thử xếp lại tối đa "
                        f"{moved_count} tiết không cố định; các tiết cố định vẫn "
                        "được giữ nguyên."
                    ),
                },
                409,
            )

        add_generated_lessons(db, p, result["lessons"])
        return finalize_generated_schedule(
            {
                "ok": True,
                "score": result["score"],
                "unscheduled": 0,
                "message": (
                    f"Đã xếp bổ sung {len(result['lessons'])} tiết từ khay và giữ "
                    "nguyên các vị trí còn hợp lệ."
                ),
            }
        )

    # Chỉ khi lịch hoàn toàn trống mới chạy bộ xếp toàn bộ.
    result = solve(db, p, tries=120)
    if result["unscheduled"] > 0:
        if result.get("proven_infeasible"):
            message = (
                "Các ràng buộc hiện tại không cho phép tạo một thời khóa biểu đầy đủ."
            )
        else:
            message = f"Chưa tìm được lịch đầy đủ trong giới hạn tìm kiếm hiện tại; còn {result['unscheduled']} tiết chưa xếp. Lịch hiện tại được giữ nguyên."
        return JSONResponse(
            {
                "ok": False,
                "score": result["score"],
                "unscheduled": result["unscheduled"],
                "message": message,
            },
            409,
        )
    for l in existing:
        db.delete(l)
    add_generated_lessons(db, p, result["lessons"])
    return finalize_generated_schedule(
        {
            "ok": True,
            "score": result["score"],
            "unscheduled": 0,
            "message": f"Đã xếp đầy đủ {len(result['lessons'])} tiết.",
        }
    )

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
        current_lessons = db.scalars(select(Lesson).where(
            Lesson.project_id == pid, Lesson.assignment_id == assignment.id
        )).all()
        current_slots = [row.slot for row in current_lessons]
        group_size = 1
        if assignment_requires_double(assignment):
            group_size = next_required_double_block_size(project, assignment, current_lessons)
            if group_size is None:
                return {"ok": True, "valid_slots": [], "move_scope": "new", "group_size": 0,
                        "message": "Cấu trúc block hiện tại không hợp lệ. Hãy tạo lại thời khóa biểu."}
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
            if slot % project.periods_per_session + group_size > project.periods_per_session:
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
                if group_size > 1 else "Chỉ các ô được đánh dấu mới có thể hoàn thành lịch hợp lệ."
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

    lessons = db.scalars(select(Lesson).where(
        Lesson.project_id == pid, Lesson.assignment_id == assignment.id
    )).all()
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
        if start % project.periods_per_session + len(moving) > project.periods_per_session:
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
    lessons = db.scalars(select(Lesson).where(
        Lesson.project_id == pid, Lesson.assignment_id == assignment.id
    )).all()
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
    proposed = [item.slot for item in lessons if item.id not in moving_ids] + target_slots
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
        item = Lesson(project_id=pid, assignment_id=assignment.id, slot=slot, block_id=block_id, block_size=block_size, locked=False)
        db.add(item)
        created.append(item)
    db.commit()
    return {
        "ok": True,
        "moved": len(created),
        "removed_ids": sorted(moving_ids),
        "moved_lessons": [
            {"id": item.id, "assignment_id": item.assignment_id, "slot": item.slot, "block_id": item.block_id, "block_size": item.block_size, "locked": item.locked}
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
    current_lessons = db.scalars(select(Lesson).where(
        Lesson.project_id == pid, Lesson.assignment_id == assignment.id
    )).all()
    if len(current_lessons) >= assignment.periods_per_week:
        return JSONResponse({"ok": False, "message": "Phân công này đã đủ số tiết/tuần."}, 409)
    group_size = 1
    if assignment_requires_double(assignment):
        group_size = next_required_double_block_size(project, assignment, current_lessons)
        if group_size is None:
            return JSONResponse({"ok": False, "message": "Cấu trúc block hiện tại không hợp lệ. Hãy tạo lại thời khóa biểu."}, 409)
    if payload.slot % project.periods_per_session + group_size > project.periods_per_session:
        return JSONResponse({"ok": False, "message": "Block tiết vượt quá cuối buổi học."}, 409)
    target_slots = list(range(payload.slot, payload.slot + group_size))
    for slot in target_slots:
        error = lesson_slot_error(db, project, assignment, slot)
        if error:
            return JSONResponse({"ok": False, "message": error}, 409)
    current_slots = [row.slot for row in current_lessons]
    if not assignment_completion_feasible(db, project, assignment, [*current_slots, *target_slots]):
        return JSONResponse({"ok": False, "message": f"Vị trí này không thể hoàn thành hợp lệ theo chế độ {assignment_pattern_label(assignment)} và các ràng buộc hiện tại."}, 409)
    block_id = new_schedule_block_id()
    created = []
    for slot in target_slots:
        row = Lesson(project_id=pid, assignment_id=assignment.id, slot=slot, block_id=block_id, block_size=group_size, locked=False)
        db.add(row); created.append(row)
    db.commit()
    return {"ok": True, "id": created[0].id, "added_lessons": [
        {"id": row.id, "assignment_id": row.assignment_id, "slot": row.slot, "block_id": row.block_id, "block_size": row.block_size, "locked": row.locked}
        for row in created
    ], "schedule_validation": schedule_ui_validation_report(db, project)}

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
    group = lesson_block_members(lessons, lesson) if assignment_requires_double(assignment) else [lesson]
    if any(item.locked or item.slot in fixed_slots for item in group):
        return JSONResponse({"ok": False, "message": "Block có tiết cố định nên không thể gỡ."}, 409)
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
        if lesson.locked
        or lesson.slot in fixed_slots.get(lesson.assignment_id, set())
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

@router.get("/api/projects/{pid}/data")
def api_data(
    pid: int,
    parts: Optional[str] = None,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    p = get_project(pid, user, db)
    requested = {item.strip() for item in (parts or "").split(",") if item.strip()}
    if not requested:
        return project_data(db, p)
    unknown = requested - {"lessons", "schedule_validation"}
    if unknown:
        raise HTTPException(400, f"Phần dữ liệu không hỗ trợ: {', '.join(sorted(unknown))}")
    result = {}
    if "lessons" in requested:
        result["lessons"] = project_lessons_data(db, p.id)
    if "schedule_validation" in requested:
        result["schedule_validation"] = schedule_ui_validation_report(db, p)
    return result
