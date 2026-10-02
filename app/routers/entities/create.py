from __future__ import annotations

from fastapi import APIRouter
from app.services.runtime import *

router = APIRouter()


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
