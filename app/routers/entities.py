from __future__ import annotations

from fastapi import APIRouter
from app.services.runtime import *

router = APIRouter()

# Shared model lookup for the generic delete endpoints. Keep this list in sync
# with the entity types accepted by the UI, including assignments.
ENTITY_MODELS = {
    "department": Department,
    "subject": Subject,
    "teacher": Teacher,
    "grade": Grade,
    "class": SchoolClass,
    "assignment": Assignment,
}

@router.post("/api/projects/{pid}/entity")
def add_entity(
    pid: int,
    payload: EntityIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    d = payload.data
    teacher_subject_ids: list[int] | None = None
    if payload.type == "department":
        name = required_text(d, "name", "Tên tổ chuyên môn", 120)
        ensure_unique_project_name(db, Department, pid, name, "Tổ chuyên môn")
        obj = Department(project_id=pid, name=name)
    elif payload.type == "subject":
        name = required_text(d, "name", "Tên môn học", 120)
        ensure_unique_project_name(db, Subject, pid, name, "Môn học")
        max_consecutive = bounded_int(
            d.get("max_consecutive"),
            min(2, project.periods_per_session),
            1,
            project.periods_per_session,
            "Số tiết liên tiếp tối đa",
        )
        short_name = (str(d.get("short_name") or "").strip() or name[:5])[:20]
        obj = Subject(
            project_id=pid,
            name=name,
            short_name=short_name,
            max_consecutive=max_consecutive,
        )
    elif payload.type == "teacher":
        name = required_text(d, "name", "Tên giáo viên", 120)
        department_id = d.get("department_id") or None
        if department_id:
            try:
                department_id = int(department_id)
            except (TypeError, ValueError) as exc:
                raise HTTPException(400, "Tổ chuyên môn không hợp lệ") from exc
            department = db.get(Department, department_id)
            if not department or department.project_id != pid:
                raise HTTPException(400, "Tổ chuyên môn không hợp lệ")
        max_periods_day = bounded_int(
            d.get("max_periods_day"),
            min(5, project.sessions * project.periods_per_session),
            1,
            project.sessions * project.periods_per_session,
            "Số tiết tối đa mỗi ngày",
        )
        short_name = (str(d.get("short_name") or "").strip() or name)[:30]
        ensure_unique_teacher_short_name(db, pid, short_name)
        teacher_subject_ids = validated_subject_ids(db, pid, d.get("subject_ids", []))
        obj = Teacher(
            project_id=pid,
            name=name,
            short_name=short_name,
            department_id=department_id,
            max_periods_day=max_periods_day,
            unavailable_json=json.dumps(valid_slots(project, d.get("unavailable", []))),
        )
    elif payload.type == "grade":
        name = required_text(d, "name", "Tên khối lớp", 80)
        ensure_unique_project_name(db, Grade, pid, name, "Khối lớp")
        obj = Grade(project_id=pid, name=name)
    elif payload.type == "class":
        name = required_text(d, "name", "Tên lớp học", 80)
        ensure_unique_project_name(db, SchoolClass, pid, name, "Lớp học")
        grade_id = d.get("grade_id") or None
        if grade_id:
            try:
                grade_id = int(grade_id)
            except (TypeError, ValueError) as exc:
                raise HTTPException(400, "Khối lớp không hợp lệ") from exc
            grade = db.get(Grade, grade_id)
            if not grade or grade.project_id != pid:
                raise HTTPException(400, "Khối lớp không hợp lệ")
        obj = SchoolClass(
            project_id=pid,
            name=name,
            grade_id=grade_id,
            unavailable_json=json.dumps(valid_slots(project, d.get("unavailable", []))),
        )
    elif payload.type == "assignment":
        class_id = required_id(d, "class_id", "Lớp học")
        subject_id = required_id(d, "subject_id", "Môn học")
        teacher_id = required_id(d, "teacher_id", "Giáo viên")
        school_class = db.get(SchoolClass, class_id)
        subject = db.get(Subject, subject_id)
        teacher = db.get(Teacher, teacher_id)
        if (
            not school_class
            or not subject
            or not teacher
            or any(x.project_id != pid for x in (school_class, subject, teacher))
        ):
            raise HTTPException(
                400, "Lớp, môn hoặc giáo viên không thuộc bộ thời khóa biểu"
            )
        allowed = db.scalar(
            select(TeacherSubject.id).where(
                TeacherSubject.project_id == pid,
                TeacherSubject.teacher_id == teacher.id,
                TeacherSubject.subject_id == subject.id,
            )
        )
        if allowed is None:
            raise HTTPException(
                409, f"{teacher.name} chưa được cấu hình dạy môn {subject.name}"
            )
        duplicate = db.scalar(
            select(Assignment).where(
                Assignment.project_id == pid,
                Assignment.class_id == school_class.id,
                Assignment.subject_id == subject.id,
            )
        )
        if duplicate is not None:
            if duplicate.teacher_id == teacher.id:
                raise HTTPException(409, "Phân công lớp – môn này đã tồn tại")
            other = db.get(Teacher, duplicate.teacher_id)
            raise HTTPException(
                409,
                f"{school_class.name} – {subject.name} đã được phân công cho {other.name if other else 'giáo viên khác'}",
            )
        periods = bounded_int(d.get("periods_per_week"), 1, 1, 40, "Số tiết mỗi tuần")
        try:
            mode = normalized_block_mode(
                d.get("block_mode", "free"), periods, subject, project
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        ensure_assignment_matches_grade_requirement(
            db, project, school_class, subject, periods, mode
        )
        ensure_teacher_load_fits(
            db,
            project,
            teacher,
            teacher_assigned_periods(db, pid, teacher.id) + periods,
        )
        ensure_class_load_fits(
            project,
            school_class,
            class_assigned_periods(db, pid, school_class.id) + periods,
        )
        ensure_assignment_hard_feasible(
            project,
            teacher,
            school_class,
            subject,
            periods,
            mode,
        )
        obj = Assignment(
            project_id=pid,
            class_id=school_class.id,
            subject_id=subject.id,
            teacher_id=teacher.id,
            periods_per_week=periods,
            block_mode=mode,
            consecutive_pattern="",
        )
    else:
        raise HTTPException(400, "Loại dữ liệu không hợp lệ")
    db.add(obj)
    db.flush()
    if payload.type == "teacher" and teacher_subject_ids is not None:
        replace_teacher_subjects(db, pid, obj.id, teacher_subject_ids)
    if payload.type == "grade":
        replace_grade_requirements(
            db, project, obj.id, d.get("subject_requirements", [])
        )
    db.commit()
    return {"ok": True, "id": obj.id}

@router.post("/api/projects/{pid}/assignments/bulk")
def add_assignments_bulk(
    pid: int,
    payload: BulkAssignmentIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    teacher = db.get(Teacher, payload.teacher_id)
    if not teacher or teacher.project_id != pid:
        raise HTTPException(400, "Giáo viên không thuộc bộ thời khóa biểu")

    class_ids = list(
        dict.fromkeys(int(value) for value in payload.class_ids if int(value) > 0)
    )
    if not class_ids:
        raise HTTPException(400, "Hãy chọn ít nhất một lớp học")

    raw_subjects = payload.subjects or [
        BulkAssignmentSubjectIn(
            subject_id=subject_id,
            periods_per_week=payload.periods_per_week,
            block_mode=payload.block_mode,
        )
        for subject_id in payload.subject_ids
    ]
    configs: dict[int, BulkAssignmentSubjectIn] = {}
    for config in raw_subjects:
        if config.subject_id > 0:
            configs[config.subject_id] = config
    subject_ids = list(configs)
    if not subject_ids:
        raise HTTPException(400, "Hãy chọn ít nhất một môn học")

    subjects = db.scalars(
        select(Subject).where(
            Subject.project_id == pid,
            Subject.id.in_(subject_ids),
        )
    ).all()
    classes = db.scalars(
        select(SchoolClass).where(
            SchoolClass.project_id == pid,
            SchoolClass.id.in_(class_ids),
        )
    ).all()
    subject_map = {item.id: item for item in subjects}
    class_map = {item.id: item for item in classes}
    if set(subject_map) != set(subject_ids):
        raise HTTPException(400, "Có môn học không thuộc bộ thời khóa biểu")
    if set(class_map) != set(class_ids):
        raise HTTPException(400, "Có lớp học không thuộc bộ thời khóa biểu")

    allowed_subject_ids = set(
        db.scalars(
            select(TeacherSubject.subject_id).where(
                TeacherSubject.project_id == pid,
                TeacherSubject.teacher_id == teacher.id,
                TeacherSubject.subject_id.in_(subject_ids),
            )
        ).all()
    )
    not_allowed = [
        subject_map[sid].name for sid in subject_ids if sid not in allowed_subject_ids
    ]
    if not_allowed:
        raise HTTPException(
            409,
            f"{teacher.name} chưa được cấu hình dạy: {', '.join(not_allowed)}",
        )

    normalized: dict[int, tuple[int, str]] = {}
    for subject_id, config in configs.items():
        subject = subject_map[subject_id]
        periods = bounded_int(
            config.periods_per_week, 1, 1, 40, f"Số tiết/tuần của {subject.name}"
        )
        try:
            mode = normalized_block_mode(config.block_mode, periods, subject, project)
        except ValueError as exc:
            raise HTTPException(400, f"{subject.name}: {exc}") from exc
        normalized[subject_id] = (periods, mode)

    existing_rows = db.scalars(
        select(Assignment).where(
            Assignment.project_id == pid,
            Assignment.subject_id.in_(subject_ids),
            Assignment.class_id.in_(class_ids),
        )
    ).all()
    existing_by_pair = defaultdict(list)
    for item in existing_rows:
        existing_by_pair[(item.subject_id, item.class_id)].append(item)
    existing_pairs = set(existing_by_pair)

    conflicts = []
    for subject_id in subject_ids:
        for class_id in class_ids:
            rows = existing_by_pair.get((subject_id, class_id), [])
            other_rows = [row for row in rows if row.teacher_id != teacher.id]
            if other_rows:
                other = db.get(Teacher, other_rows[0].teacher_id)
                conflicts.append(
                    f"{class_map[class_id].name} – {subject_map[subject_id].name} "
                    f"({other.name if other else 'giáo viên khác'})"
                )
    if conflicts:
        preview = "; ".join(conflicts[:5])
        suffix = f"; và {len(conflicts) - 5} cặp khác" if len(conflicts) > 5 else ""
        raise HTTPException(
            409,
            f"Không thể tạo vì môn của lớp đã được phân công cho giáo viên khác: {preview}{suffix}.",
        )

    configured_grade_ids = set(
        db.scalars(
            select(GradeSubjectRequirement.grade_id).where(
                GradeSubjectRequirement.project_id == pid
            )
        ).all()
    )
    curriculum_conflicts = []
    existing_config_conflicts = []
    for class_id in class_ids:
        school_class = class_map[class_id]
        for subject_id in subject_ids:
            periods, mode = normalized[subject_id]
            rows = existing_by_pair.get((subject_id, class_id), [])
            same_teacher_rows = [row for row in rows if row.teacher_id == teacher.id]
            requirement = grade_requirement_for_assignment(
                db, pid, school_class, subject_id
            )

            if requirement is not None:
                required_periods = int(requirement.periods_per_week)
                required_mode = requirement.block_mode or "free"
                if same_teacher_rows:
                    stale_rows = [
                        row
                        for row in same_teacher_rows
                        if int(row.periods_per_week) != required_periods
                        or (row.block_mode or "free") != required_mode
                    ]
                    if stale_rows:
                        current = stale_rows[0]
                        curriculum_conflicts.append(
                            f"{school_class.name} – {subject_map[subject_id].name}: "
                            f"phân công hiện có {int(current.periods_per_week)} tiết/tuần · "
                            f"{block_mode_text(current.block_mode or 'free')}, "
                            f"chương trình yêu cầu {required_periods} tiết/tuần · "
                            f"{block_mode_text(required_mode)}"
                        )
                elif periods != required_periods or mode != required_mode:
                    curriculum_conflicts.append(
                        f"{school_class.name} – {subject_map[subject_id].name}: "
                        f"yêu cầu {required_periods} tiết/tuần · {block_mode_text(required_mode)}, "
                        f"đang nhập {periods} tiết/tuần · {block_mode_text(mode)}"
                    )
            elif school_class.grade_id in configured_grade_ids:
                curriculum_conflicts.append(
                    f"{school_class.name} – {subject_map[subject_id].name}: "
                    "môn không thuộc chương trình khối đã cấu hình"
                )

            if same_teacher_rows:
                mismatched_rows = [
                    row
                    for row in same_teacher_rows
                    if int(row.periods_per_week) != periods
                    or (row.block_mode or "free") != mode
                ]
                if mismatched_rows:
                    current = mismatched_rows[0]
                    existing_config_conflicts.append(
                        f"{school_class.name} – {subject_map[subject_id].name}: "
                        f"đang có {int(current.periods_per_week)} tiết/tuần · "
                        f"{block_mode_text(current.block_mode or 'free')}, "
                        f"đang chọn {periods} tiết/tuần · {block_mode_text(mode)}"
                    )

    if curriculum_conflicts:
        preview = "; ".join(curriculum_conflicts[:5])
        suffix = (
            f"; và {len(curriculum_conflicts) - 5} cặp khác"
            if len(curriculum_conflicts) > 5
            else ""
        )
        raise HTTPException(
            409,
            "Không thể tiếp tục vì có phân công chưa khớp chương trình chuẩn theo khối: "
            f"{preview}{suffix}. Hãy chọn môn thuộc chương trình, cập nhật chương trình khối "
            "hoặc sửa phân công hiện có trước khi phân công hàng loạt.",
        )

    if existing_config_conflicts:
        preview = "; ".join(existing_config_conflicts[:5])
        suffix = (
            f"; và {len(existing_config_conflicts) - 5} cặp khác"
            if len(existing_config_conflicts) > 5
            else ""
        )
        raise HTTPException(
            409,
            "Có phân công đã tồn tại nhưng cấu hình khác lựa chọn hiện tại: "
            f"{preview}{suffix}. Hãy sửa phân công hiện có hoặc bỏ cặp đó khỏi lần phân công này.",
        )

    added_periods = 0
    added_periods_by_class = Counter()
    for subject_id in subject_ids:
        periods, _ = normalized[subject_id]
        for class_id in class_ids:
            if (subject_id, class_id) not in existing_pairs:
                added_periods += periods
                added_periods_by_class[class_id] += periods
    current_periods = teacher_assigned_periods(db, pid, teacher.id)
    ensure_teacher_load_fits(db, project, teacher, current_periods + added_periods)
    for class_id, class_added_periods in added_periods_by_class.items():
        ensure_class_load_fits(
            project,
            class_map[class_id],
            class_assigned_periods(db, pid, class_id) + class_added_periods,
        )

    created = 0
    skipped = 0
    for subject_id in subject_ids:
        periods, mode = normalized[subject_id]
        for class_id in class_ids:
            if (subject_id, class_id) in existing_pairs:
                skipped += 1
                continue
            ensure_assignment_hard_feasible(
                project,
                teacher,
                class_map[class_id],
                subject_map[subject_id],
                periods,
                mode,
            )
            db.add(
                Assignment(
                    project_id=pid,
                    class_id=class_id,
                    subject_id=subject_id,
                    teacher_id=teacher.id,
                    periods_per_week=periods,
                    block_mode=mode,
                    consecutive_pattern="",
                )
            )
            created += 1

    db.commit()
    if created and skipped:
        message = f"Đã tạo {created} phân công; bỏ qua {skipped} phân công đã tồn tại."
    elif created:
        message = f"Đã tạo {created} phân công."
    else:
        message = f"Không tạo mới: {skipped} phân công đã tồn tại."
    return {"ok": True, "created": created, "skipped": skipped, "message": message}

@router.put("/api/projects/{pid}/entity/{typ}/{eid}")
def update_entity(
    pid: int,
    typ: str,
    eid: int,
    payload: EntityIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    if payload.type != typ or typ not in {
        "department",
        "subject",
        "teacher",
        "grade",
        "class",
    }:
        raise HTTPException(400, "Loại dữ liệu không hợp lệ")
    model = {
        "department": Department,
        "subject": Subject,
        "teacher": Teacher,
        "grade": Grade,
        "class": SchoolClass,
    }[typ]
    obj = db.get(model, eid)
    if not obj or obj.project_id != pid:
        raise HTTPException(404, "Không tìm thấy dữ liệu cần sửa")
    d = payload.data
    synced_assignments = 0
    displaced_lesson_ids: list[int] = []
    removed_extra_assignments = 0
    missing_grade_assignments: list[str] = []
    name_limit = {
        "department": 120,
        "subject": 120,
        "teacher": 120,
        "grade": 80,
        "class": 80,
    }[typ]
    name = bounded_text(d.get("name", ""), "Tên", name_limit)
    if typ == "department":
        ensure_unique_project_name(
            db, Department, pid, name, "Tổ chuyên môn", exclude_id=obj.id
        )
        obj.name = name
    elif typ == "subject":
        ensure_unique_project_name(db, Subject, pid, name, "Môn học", exclude_id=obj.id)
        short_name = bounded_text(d.get("short_name", ""), "Tên rút gọn", 20)
        new_max_consecutive = bounded_int(
            d.get("max_consecutive"),
            min(obj.max_consecutive, project.periods_per_session),
            1,
            project.periods_per_session,
            "Số tiết liên tiếp tối đa",
        )
        assignments = db.scalars(
            select(Assignment).where(
                Assignment.project_id == pid,
                Assignment.subject_id == obj.id,
            )
        ).all()
        incompatible_assignments = [
            assignment.id
            for assignment in assignments
            if assignment_prefers_double(assignment)
            and assignment.periods_per_week >= 2
            and new_max_consecutive < 2
        ]

        for assignment in assignments:
            teacher = db.get(Teacher, assignment.teacher_id)
            school_class = db.get(SchoolClass, assignment.class_id)
            if not teacher or not school_class:
                raise HTTPException(
                    409,
                    "Không thể đổi giới hạn tiết liên tiếp vì có phân công tham chiếu dữ liệu không còn tồn tại.",
                )
            ensure_assignment_hard_feasible(
                project,
                teacher,
                school_class,
                obj,
                assignment.periods_per_week,
                assignment.block_mode,
                max_consecutive=new_max_consecutive,
            )
        incompatible_grade_requirements = db.scalars(
            select(GradeSubjectRequirement).where(
                GradeSubjectRequirement.project_id == pid,
                GradeSubjectRequirement.subject_id == obj.id,
                GradeSubjectRequirement.block_mode == "required_double",
            )
        ).all()
        incompatible_grade_requirements = [
            row.id
            for row in incompatible_grade_requirements
            if not required_double_structure_feasible(
                project, row.periods_per_week, new_max_consecutive
            )
        ]

        assignment_by_id = {assignment.id: assignment for assignment in assignments}
        periods_by_class_session = defaultdict(list)
        periods_per_day = project.sessions * project.periods_per_session
        if assignment_by_id:
            lessons = db.scalars(
                select(Lesson).where(
                    Lesson.project_id == pid,
                    Lesson.assignment_id.in_(list(assignment_by_id)),
                )
            ).all()
            for lesson in lessons:
                assignment = assignment_by_id.get(lesson.assignment_id)
                if not assignment:
                    continue
                day = lesson.slot // periods_per_day
                inside_day = lesson.slot % periods_per_day
                session = inside_day // project.periods_per_session
                period = inside_day % project.periods_per_session
                periods_by_class_session[(assignment.class_id, day, session)].append(
                    period
                )

        violating_class_sessions = 0
        for periods in periods_by_class_session.values():
            longest = run = 0
            previous = None
            for period in sorted(set(periods)):
                run = run + 1 if previous is not None and period == previous + 1 else 1
                longest = max(longest, run)
                previous = period
            if longest > new_max_consecutive:
                violating_class_sessions += 1

        if (
            incompatible_assignments
            or incompatible_grade_requirements
            or violating_class_sessions
        ):
            details = []
            if incompatible_assignments:
                details.append(
                    f"{len(incompatible_assignments)} phân công đang dùng chế độ tiết đôi"
                )
            if incompatible_grade_requirements:
                details.append(
                    f"{len(incompatible_grade_requirements)} cấu hình chương trình khối bắt buộc tiết đôi "
                    "sẽ không còn cách xếp hợp lệ"
                )
            if violating_class_sessions:
                details.append(
                    f"{violating_class_sessions} buổi của lớp đang có cụm môn học dài hơn"
                )
            raise HTTPException(
                409,
                f"Không thể giảm còn {new_max_consecutive} tiết liên tiếp vì "
                + " và ".join(details)
                + ". Hãy điều chỉnh phân công, chương trình khối hoặc lịch hiện tại trước.",
            )
        obj.name = name
        obj.short_name = short_name
        obj.max_consecutive = new_max_consecutive
    elif typ == "teacher":
        short_name = bounded_text(d.get("short_name", ""), "Tên ngắn", 30)
        ensure_unique_teacher_short_name(db, pid, short_name, exclude_id=obj.id)
        if "department_id" in d:
            department_id = d.get("department_id") or None
            if department_id is not None:
                try:
                    department_id = int(department_id)
                except (TypeError, ValueError) as exc:
                    raise HTTPException(400, "Tổ chuyên môn không hợp lệ") from exc
                department = db.get(Department, department_id)
                if not department or department.project_id != pid:
                    raise HTTPException(400, "Tổ chuyên môn không hợp lệ")
        else:
            department_id = obj.department_id
        new_max_periods_day = bounded_int(
            d.get("max_periods_day"),
            min(obj.max_periods_day, project.sessions * project.periods_per_session),
            1,
            project.sessions * project.periods_per_session,
            "Số tiết tối đa mỗi ngày",
        )
        assignment_ids = set(
            db.scalars(
                select(Assignment.id).where(
                    Assignment.project_id == pid,
                    Assignment.teacher_id == obj.id,
                )
            ).all()
        )
        if assignment_ids:
            ppd = project.sessions * project.periods_per_session
            daily_counts = Counter(
                slot // ppd
                for slot in db.scalars(
                    select(Lesson.slot).where(
                        Lesson.project_id == pid,
                        Lesson.assignment_id.in_(assignment_ids),
                    )
                ).all()
            )
            highest_current = max(daily_counts.values(), default=0)
            if highest_current > new_max_periods_day:
                raise HTTPException(
                    409,
                    f"Không thể giảm còn {new_max_periods_day} tiết/ngày vì lịch hiện tại có ngày giáo viên đang dạy {highest_current} tiết. Hãy điều chỉnh lịch trước.",
                )
        assigned_total = teacher_assigned_periods(db, pid, obj.id)
        ensure_teacher_load_fits(
            db, project, obj, assigned_total, max_periods_day=new_max_periods_day
        )
        for assignment in db.scalars(
            select(Assignment).where(
                Assignment.project_id == pid,
                Assignment.teacher_id == obj.id,
            )
        ).all():
            school_class = db.get(SchoolClass, assignment.class_id)
            subject = db.get(Subject, assignment.subject_id)
            if school_class and subject:
                ensure_assignment_hard_feasible(
                    project,
                    obj,
                    school_class,
                    subject,
                    assignment.periods_per_week,
                    assignment.block_mode,
                    max_periods_day=new_max_periods_day,
                )
        if "subject_ids" in d:
            teacher_subject_ids = validated_subject_ids(db, pid, d.get("subject_ids"))
            assigned_subject_ids = set(
                db.scalars(
                    select(Assignment.subject_id).where(
                        Assignment.project_id == pid,
                        Assignment.teacher_id == obj.id,
                    )
                ).all()
            )
            removed_in_use = assigned_subject_ids - set(teacher_subject_ids)
            if removed_in_use:
                names = db.scalars(
                    select(Subject.name).where(Subject.id.in_(removed_in_use))
                ).all()
                raise HTTPException(
                    409,
                    "Không thể bỏ môn đang có phân công: "
                    + ", ".join(names)
                    + ". Hãy xóa/chuyển phân công trước.",
                )
            replace_teacher_subjects(db, pid, obj.id, teacher_subject_ids)
        obj.name = name
        obj.short_name = short_name
        obj.department_id = department_id
        obj.max_periods_day = new_max_periods_day
    elif typ == "grade":
        ensure_unique_project_name(db, Grade, pid, name, "Khối lớp", exclude_id=obj.id)
        if "subject_requirements" in d:
            proposed_configs = normalized_grade_requirements(
                db, project, d.get("subject_requirements", [])
            )
            current_rows = db.scalars(
                select(GradeSubjectRequirement).where(
                    GradeSubjectRequirement.project_id == pid,
                    GradeSubjectRequirement.grade_id == obj.id,
                )
            ).all()
            current_configs = sorted(
                (row.subject_id, int(row.periods_per_week), row.block_mode or "free")
                for row in current_rows
            )
            if sorted(proposed_configs) != current_configs:
                # Save the curriculum first so its new subjects can be assigned.
                # Generate/share/export still reject an incomplete curriculum.
                missing_grade_assignments = grade_requirement_missing_assignments(
                    db, project, obj.id, proposed_configs
                )

                extra_assignments = grade_requirement_extra_assignments(
                    db,
                    project,
                    obj.id,
                    configs=proposed_configs,
                )
                if extra_assignments and d.get("remove_extra_assignments") is not True:
                    preview = "; ".join(
                        f"{item['class_name']} – {item['subject_name']}"
                        for item in extra_assignments[:5]
                    )
                    suffix = (
                        f"; và {len(extra_assignments) - 5} phân công khác"
                        if len(extra_assignments) > 5
                        else ""
                    )
                    return JSONResponse(
                        {
                            "ok": False,
                            "reason": "grade_program_extra_assignments",
                            "extra_assignments": extra_assignments,
                            "message": (
                                f"Chương trình mới của {obj.name} sẽ loại bỏ các phân công: "
                                f"{preview}{suffix}. Nếu tiếp tục, các phân công này và "
                                "các tiết đã xếp/ghim tương ứng sẽ bị xóa."
                            ),
                        },
                        409,
                    )

                synced_assignments += sync_assignments_to_grade_requirements(
                    db, project, obj.id, proposed_configs,
                    displaced_lesson_ids=displaced_lesson_ids,
                )
                for item in extra_assignments:
                    assignment = db.get(Assignment, item["assignment_id"])
                    if not assignment or assignment.project_id != pid:
                        continue
                    delete_entity_related_rows(db, "assignment", assignment.id)
                    db.delete(assignment)
                    removed_extra_assignments += 1
            replace_grade_requirements(
                db, project, obj.id, d.get("subject_requirements", [])
            )
        obj.name = name
    else:
        ensure_unique_project_name(
            db, SchoolClass, pid, name, "Lớp học", exclude_id=obj.id
        )
        if "grade_id" in d:
            grade_id = d.get("grade_id") or None
            if grade_id is not None:
                try:
                    grade_id = int(grade_id)
                except (TypeError, ValueError) as exc:
                    raise HTTPException(400, "Khối lớp không hợp lệ") from exc
                grade = db.get(Grade, grade_id)
                if not grade or grade.project_id != pid:
                    raise HTTPException(400, "Khối lớp không hợp lệ")
        else:
            grade_id = obj.grade_id
        if grade_id != obj.grade_id and grade_id is not None:
            proposed_rows = db.scalars(
                select(GradeSubjectRequirement).where(
                    GradeSubjectRequirement.project_id == pid,
                    GradeSubjectRequirement.grade_id == grade_id,
                )
            ).all()
            proposed_configs = [
                (row.subject_id, int(row.periods_per_week), row.block_mode or "free")
                for row in proposed_rows
            ]
            missing_grade_assignments = grade_requirement_missing_assignments(
                db,
                project,
                grade_id,
                proposed_configs,
                classes=[obj],
            )

            extra_assignments = grade_requirement_extra_assignments(
                db, project, grade_id, classes=[obj]
            )
            if extra_assignments and d.get("remove_extra_assignments") is not True:
                grade = db.get(Grade, grade_id)
                preview = "; ".join(
                    f"{item['class_name']} – {item['subject_name']}"
                    for item in extra_assignments[:5]
                )
                suffix = (
                    f"; và {len(extra_assignments) - 5} phân công khác"
                    if len(extra_assignments) > 5
                    else ""
                )
                return JSONResponse(
                    {
                        "ok": False,
                        "reason": "class_grade_extra_assignments",
                        "extra_assignments": extra_assignments,
                        "message": (
                            f"{obj.name} đang có phân công không thuộc chương trình "
                            f"{grade.name if grade else 'khối mới'}: {preview}{suffix}. "
                            "Nếu tiếp tục, các phân công này và các tiết đã xếp/ghim tương ứng sẽ bị xóa."
                        ),
                    },
                    409,
                )

            synced_assignments += sync_assignments_to_grade_requirements(
                db,
                project,
                grade_id,
                proposed_configs,
                classes=[obj],
                displaced_lesson_ids=displaced_lesson_ids,
            )
            if extra_assignments:
                for item in extra_assignments:
                    assignment = db.get(Assignment, item["assignment_id"])
                    if not assignment or assignment.project_id != pid:
                        continue
                    delete_entity_related_rows(db, "assignment", assignment.id)
                    db.delete(assignment)
                    removed_extra_assignments += 1
        obj.name = name
        obj.grade_id = grade_id
    confirmation = schedule_displacement_confirmation(
        db, displaced_lesson_ids,
        confirmed=d.get("confirm_displacement") is True,
        confirmed_ids=d.get("confirmed_displaced_lesson_ids"),
    )
    if confirmation is not None:
        return confirmation
    db.commit()
    return {
        "ok": True,
        "displaced_lessons": len(set(displaced_lesson_ids)),
        "synced_assignments": synced_assignments,
        "removed_extra_assignments": removed_extra_assignments,
        "missing_grade_assignments": missing_grade_assignments,
        "missing_grade_assignments_count": len(missing_grade_assignments),
    }

@router.put("/api/projects/{pid}/assignments/{assignment_id}")
def update_assignment(
    pid: int,
    assignment_id: int,
    payload: AssignmentUpdateIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    assignment = db.get(Assignment, assignment_id)
    if not assignment or assignment.project_id != pid:
        raise HTTPException(404)
    periods = bounded_int(payload.periods_per_week, 1, 1, 40, "Số tiết mỗi tuần")
    lessons = db.scalars(
        select(Lesson).where(Lesson.assignment_id == assignment.id)
    ).all()
    scheduled = len(lessons)
    original_lesson_ids = {lesson.id for lesson in lessons}
    subject = db.get(Subject, assignment.subject_id)
    if not subject or subject.project_id != pid:
        raise HTTPException(409, "Môn học của phân công không còn tồn tại")
    try:
        mode = normalized_block_mode(payload.block_mode, periods, subject, project)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    old_periods = assignment.periods_per_week
    old_mode = assignment.block_mode
    if periods < scheduled and not (
        old_mode == "required_double" and mode == "required_double"
    ):
        return JSONResponse(
            {
                "ok": False,
                "message": f"Đang có {scheduled} tiết trên lịch. Hãy gỡ bớt tiết trước khi giảm số tiết/tuần.",
            },
            409,
        )
    teacher = db.get(Teacher, assignment.teacher_id)
    if not teacher or teacher.project_id != pid:
        raise HTTPException(409, "Giáo viên của phân công không còn tồn tại")
    projected_total = (
        teacher_assigned_periods(db, pid, teacher.id) - old_periods + periods
    )
    ensure_teacher_load_fits(db, project, teacher, projected_total)
    school_class = db.get(SchoolClass, assignment.class_id)
    if not school_class or school_class.project_id != pid:
        raise HTTPException(409, "Lớp của phân công không còn tồn tại")
    ensure_assignment_matches_grade_requirement(
        db, project, school_class, subject, periods, mode
    )
    projected_class_total = (
        class_assigned_periods(db, pid, school_class.id) - old_periods + periods
    )
    ensure_class_load_fits(project, school_class, projected_class_total)
    ensure_assignment_hard_feasible(
        project,
        teacher,
        school_class,
        subject,
        periods,
        mode,
    )
    periods_changed = periods != old_periods
    mode_changed = mode != old_mode

    # Reconcile transactionally; any removal must be confirmed before commit.
    assignment.periods_per_week = periods
    assignment.block_mode = mode
    assignment.consecutive_pattern = ""

    if mode_changed or (periods_changed and assignment_requires_double(assignment)):
        lessons, block_error = reconcile_assignment_lesson_blocks(
            db, project, assignment, lessons, old_mode=old_mode
        )
        if block_error:
            db.rollback()
            return JSONResponse({"ok": False, "message": block_error}, 409)
        fixed_error = normalize_assignment_fixed_rows(db, project, assignment, lessons)
        if fixed_error:
            db.rollback()
            return JSONResponse({"ok": False, "message": fixed_error}, 409)

    # Chỉ các thay đổi ảnh hưởng cấu trúc cụm mới cần chứng minh rằng những tiết
    # đã xếp vẫn có ít nhất một cách hoàn thành. Tăng số tiết ở chế độ tự do/
    # ưu tiên chỉ tạo phần còn thiếu trong khay và giữ nguyên toàn bộ lịch cũ.
    if (
        mode_changed or (periods_changed and assignment_requires_double(assignment))
    ) and not assignment_completion_feasible(
        db, project, assignment, [lesson.slot for lesson in lessons]
    ):
        db.rollback()
        return JSONResponse(
            {
                "ok": False,
                "message": "Không thể áp dụng thay đổi vì các tiết hiện có không thể hoàn thành hợp lệ theo chế độ mới và các ràng buộc hiện tại. Lịch cũ được giữ nguyên.",
            },
            409,
        )

    displaced_lesson_ids = sorted(original_lesson_ids - {lesson.id for lesson in lessons})
    confirmation = schedule_displacement_confirmation(
        db, displaced_lesson_ids,
        confirmed=payload.confirm_displacement,
        confirmed_ids=payload.confirmed_displaced_lesson_ids,
    )
    if confirmation is not None:
        return confirmation
    scheduled_preserved = len(lessons)
    db.commit()
    return {
        "ok": True,
        "scheduled_preserved": scheduled_preserved,
        "displaced_lessons": len(displaced_lesson_ids),
    }

@router.delete("/api/projects/{pid}/entity/{typ}/{eid}")
def delete_entity(
    pid: int,
    typ: str,
    eid: int,
    payload: EntityDeleteIn | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    get_project_for_update(pid, user, db)
    model = ENTITY_MODELS.get(typ)
    if not model:
        raise HTTPException(400)
    obj = db.get(model, eid)
    if not obj or obj.project_id != pid:
        raise HTTPException(404)
    if typ == "assignment":
        impact = assignment_delete_impact(db, [eid])
        confirmation = assignment_delete_confirmation(impact, payload)
        if confirmation is not None:
            return confirmation
    if entity_delete_dependency(db, typ, eid) is not None:
        return JSONResponse(
            {"ok": False, "message": "Không thể xóa vì dữ liệu đang được sử dụng."}, 409
        )
    delete_entity_related_rows(db, typ, eid)
    db.delete(obj)
    db.commit()
    return {"ok": True}

@router.delete("/api/projects/{pid}/entities/bulk")
def delete_entities_bulk(
    pid: int,
    payload: BulkEntityDeleteIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    """Xóa nhiều dòng cùng loại, nhưng không bỏ qua kiểm tra phụ thuộc."""
    get_project_for_update(pid, user, db)
    typ = (payload.type or "").strip().lower()
    model = ENTITY_MODELS.get(typ)
    if not model:
        raise HTTPException(400, "Loại dữ liệu không hợp lệ")

    ids = []
    seen = set()
    for raw_id in payload.ids:
        try:
            eid = int(raw_id)
        except (TypeError, ValueError):
            continue
        if eid > 0 and eid not in seen:
            seen.add(eid)
            ids.append(eid)
    if not ids:
        raise HTTPException(400, "Chưa chọn dữ liệu để xóa")
    if len(ids) > 500:
        raise HTTPException(400, "Mỗi lần chỉ được xóa tối đa 500 mục")

    rows = db.scalars(
        select(model).where(model.project_id == pid, model.id.in_(ids))
    ).all()
    row_by_id = {row.id: row for row in rows}
    if typ == "assignment" and row_by_id:
        impact = assignment_delete_impact(db, list(row_by_id))
        confirmation = assignment_delete_confirmation(
            impact, payload, assignment_count=len(row_by_id)
        )
        if confirmation is not None:
            return confirmation
    blocked_ids = entity_delete_dependency_ids(db, typ, list(row_by_id))
    deleted_ids = []
    skipped = []
    for eid in ids:
        obj = row_by_id.get(eid)
        if obj is None:
            skipped.append(
                {"id": eid, "reason": "Không còn tồn tại trong bộ thời khóa biểu này."}
            )
            continue
        if eid in blocked_ids:
            skipped.append(
                {
                    "id": eid,
                    "name": str(getattr(obj, "name", "") or ""),
                    "reason": "Dữ liệu đang được sử dụng.",
                }
            )
            continue
        delete_entity_related_rows(db, typ, eid)
        db.delete(obj)
        deleted_ids.append(eid)

    if not deleted_ids:
        db.rollback()
        return JSONResponse(
            {
                "ok": False,
                "deleted": 0,
                "skipped": skipped,
                "message": "Không có mục nào được xóa. Các mục đã chọn đang được sử dụng hoặc không còn tồn tại.",
            },
            409,
        )

    db.commit()
    message = f"Đã xóa {len(deleted_ids)} mục."
    if skipped:
        message += (
            f" Bỏ qua {len(skipped)} mục đang được sử dụng hoặc không còn tồn tại."
        )
    return {
        "ok": True,
        "deleted": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "skipped": skipped,
        "message": message,
    }

