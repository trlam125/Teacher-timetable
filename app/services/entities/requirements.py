from __future__ import annotations

from app.services.foundation import *
from app.services.web import *
from app.services.schedule_service import *

from .validation import *


def assignment_project_reference_issues(
    db: Session, project_id: int, assignments: list[Assignment]
) -> list[dict]:
    """Phát hiện phân công tham chiếu lớp/môn/GV mất hoặc thuộc project khác."""
    if not assignments:
        return []
    teacher_ids = {row.teacher_id for row in assignments}
    class_ids = {row.class_id for row in assignments}
    subject_ids = {row.subject_id for row in assignments}
    teacher_projects = (
        dict(
            db.execute(
                select(Teacher.id, Teacher.project_id).where(
                    Teacher.id.in_(teacher_ids)
                )
            ).all()
        )
        if teacher_ids
        else {}
    )
    class_projects = (
        dict(
            db.execute(
                select(SchoolClass.id, SchoolClass.project_id).where(
                    SchoolClass.id.in_(class_ids)
                )
            ).all()
        )
        if class_ids
        else {}
    )
    subject_projects = (
        dict(
            db.execute(
                select(Subject.id, Subject.project_id).where(
                    Subject.id.in_(subject_ids)
                )
            ).all()
        )
        if subject_ids
        else {}
    )

    specs = (
        ("teacher_id", "Giáo viên", teacher_projects),
        ("class_id", "Lớp", class_projects),
        ("subject_id", "Môn", subject_projects),
    )
    issues = []
    for assignment in assignments:
        invalid_refs = []
        for field, label, projects_by_id in specs:
            reference_id = getattr(assignment, field)
            actual_project_id = projects_by_id.get(reference_id)
            if actual_project_id != project_id:
                invalid_refs.append(
                    {
                        "field": field,
                        "label": label,
                        "id": reference_id,
                        "actual_project_id": actual_project_id,
                    }
                )
        if invalid_refs:
            issues.append(
                {
                    "assignment_id": assignment.id,
                    "invalid_refs": invalid_refs,
                }
            )
    return issues


def schedule_teacher_capacity_issues(
    db: Session,
    project: Project,
    assignments: list[Assignment],
) -> list[dict]:
    """Return teacher loads that cannot fit even before conflict solving.

    This necessary (but not sufficient) feasibility check also covers legacy
    and imported data that predates assignment-time load validation. It lets the
    scheduler explain the real constraint instead of appearing to skip teachers.
    """
    assigned_by_teacher = Counter()
    for assignment in assignments:
        assigned_by_teacher[assignment.teacher_id] += int(
            assignment.periods_per_week or 0
        )

    project_blocked = set(
        valid_slots(
            project,
            parse_slots(project.blocked_slots_json),
            strict=False,
        )
    )
    issues = []
    for teacher_id, assigned in assigned_by_teacher.items():
        teacher = db.get(Teacher, teacher_id)
        if not teacher:
            continue
        capacity = teacher_week_capacity(
            project,
            teacher,
            project_blocked_slots=project_blocked,
        )
        if assigned > capacity:
            issues.append(
                {
                    "teacher_id": teacher.id,
                    "teacher_name": teacher.name,
                    "assigned": assigned,
                    "capacity": capacity,
                    "excess": assigned - capacity,
                }
            )
    return sorted(issues, key=lambda item: (-item["excess"], item["teacher_name"]))


def schedule_class_capacity_issues(
    project: Project,
    classes: list[SchoolClass],
    assignments: list[Assignment],
) -> list[dict]:
    assigned_by_class = Counter()
    for assignment in assignments:
        assigned_by_class[assignment.class_id] += int(assignment.periods_per_week or 0)
    issues = []
    for school_class in classes:
        assigned = assigned_by_class[school_class.id]
        if not assigned:
            continue
        capacity = class_week_capacity(project, school_class)
        if assigned > capacity:
            issues.append(
                {
                    "class_id": school_class.id,
                    "class_name": school_class.name,
                    "assigned": assigned,
                    "capacity": capacity,
                    "excess": assigned - capacity,
                }
            )
    return sorted(issues, key=lambda item: (-item["excess"], item["class_name"]))


def grade_requirement_assignment_issues(
    db: Session,
    project: Project,
    assignments: list[Assignment] | None = None,
    classes: list[SchoolClass] | None = None,
) -> list[dict]:
    """Return missing, mismatched and extra assignments for configured curricula.

    A grade is treated as having a strict curriculum only when it has at least one
    ``GradeSubjectRequirement`` row. Grades without any configured requirement keep
    the legacy/open behaviour, so their assignments are not reported as ``extra``.
    """
    requirements = db.scalars(
        select(GradeSubjectRequirement).where(
            GradeSubjectRequirement.project_id == project.id,
        )
    ).all()
    if not requirements:
        return []
    if assignments is None:
        assignments = db.scalars(
            select(Assignment).where(Assignment.project_id == project.id)
        ).all()
    if classes is None:
        classes = db.scalars(
            select(SchoolClass).where(SchoolClass.project_id == project.id)
        ).all()

    requirement_by_grade = defaultdict(list)
    required_subject_ids_by_grade = defaultdict(set)
    for requirement in requirements:
        requirement_by_grade[requirement.grade_id].append(requirement)
        required_subject_ids_by_grade[requirement.grade_id].add(requirement.subject_id)

    assignment_by_pair = {(row.class_id, row.subject_id): row for row in assignments}
    assignments_by_class = defaultdict(list)
    for assignment in assignments:
        assignments_by_class[assignment.class_id].append(assignment)

    subject_ids = {row.subject_id for row in requirements}
    subject_ids.update(row.subject_id for row in assignments)
    subjects = (
        {
            row.id: row
            for row in db.scalars(
                select(Subject).where(
                    Subject.project_id == project.id,
                    Subject.id.in_(subject_ids),
                )
            ).all()
        }
        if subject_ids
        else {}
    )
    grade_ids = {row.grade_id for row in requirements}
    grades = (
        {
            row.id: row
            for row in db.scalars(
                select(Grade).where(
                    Grade.project_id == project.id,
                    Grade.id.in_(grade_ids),
                )
            ).all()
        }
        if grade_ids
        else {}
    )

    issues: list[dict] = []
    for school_class in classes:
        if school_class.grade_id is None:
            continue
        grade_requirements = requirement_by_grade.get(school_class.grade_id, [])
        if not grade_requirements:
            # No configured curriculum for this grade: assignments remain open-ended.
            continue
        grade = grades.get(school_class.grade_id)
        required_subject_ids = required_subject_ids_by_grade[school_class.grade_id]

        for requirement in grade_requirements:
            assignment = assignment_by_pair.get(
                (school_class.id, requirement.subject_id)
            )
            subject = subjects.get(requirement.subject_id)
            base = {
                "class_id": school_class.id,
                "class_name": school_class.name,
                "grade_id": school_class.grade_id,
                "grade_name": grade.name if grade else "?",
                "subject_id": requirement.subject_id,
                "subject_name": subject.name if subject else "?",
                "required_periods": int(requirement.periods_per_week),
                "required_mode": requirement.block_mode or "free",
            }
            if assignment is None:
                issues.append({**base, "issue_type": "missing"})
                continue
            actual_periods = int(assignment.periods_per_week)
            actual_mode = assignment.block_mode or "free"
            if actual_periods != int(requirement.periods_per_week) or actual_mode != (
                requirement.block_mode or "free"
            ):
                issues.append(
                    {
                        **base,
                        "issue_type": "mismatch",
                        "assignment_id": assignment.id,
                        "assigned_periods": actual_periods,
                        "assigned_mode": actual_mode,
                    }
                )

        for assignment in assignments_by_class.get(school_class.id, []):
            if assignment.subject_id in required_subject_ids:
                continue
            subject = subjects.get(assignment.subject_id)
            issues.append(
                {
                    "issue_type": "extra",
                    "assignment_id": assignment.id,
                    "class_id": school_class.id,
                    "class_name": school_class.name,
                    "grade_id": school_class.grade_id,
                    "grade_name": grade.name if grade else "?",
                    "subject_id": assignment.subject_id,
                    "subject_name": subject.name if subject else "?",
                    "assigned_periods": int(assignment.periods_per_week),
                    "assigned_mode": assignment.block_mode or "free",
                }
            )

    issue_order = {"missing": 0, "mismatch": 1, "extra": 2}
    issues.sort(
        key=lambda item: (
            item["class_name"],
            item["subject_name"],
            issue_order.get(item["issue_type"], 99),
        )
    )
    return issues


def block_mode_text(mode: str) -> str:
    return {
        "free": "Tự do",
        "preferred_double": "Ưu tiên tiết đôi",
        "required_double": "Bắt buộc tiết đôi",
    }.get(mode or "free", mode or "Tự do")


def grade_requirement_for_assignment(
    db: Session,
    project_id: int,
    school_class: SchoolClass,
    subject_id: int,
) -> GradeSubjectRequirement | None:
    if school_class.grade_id is None:
        return None
    return db.scalar(
        select(GradeSubjectRequirement).where(
            GradeSubjectRequirement.project_id == project_id,
            GradeSubjectRequirement.grade_id == school_class.grade_id,
            GradeSubjectRequirement.subject_id == subject_id,
        )
    )


def ensure_assignment_matches_grade_requirement(
    db: Session,
    project: Project,
    school_class: SchoolClass,
    subject: Subject,
    periods: int,
    mode: str,
) -> None:
    requirement = grade_requirement_for_assignment(
        db, project.id, school_class, subject.id
    )
    if requirement is None:
        if school_class.grade_id is None:
            return
        grade_has_program = db.scalar(
            select(GradeSubjectRequirement.id).where(
                GradeSubjectRequirement.project_id == project.id,
                GradeSubjectRequirement.grade_id == school_class.grade_id,
            )
        )
        if grade_has_program is None:
            # A grade with no configured curriculum remains open-ended.
            return
        grade = db.get(Grade, school_class.grade_id)
        raise HTTPException(
            409,
            f"{school_class.name} – {subject.name} không thuộc chương trình "
            f"{grade.name if grade else 'khối'} đã cấu hình. "
            "Hãy thêm môn vào chương trình khối hoặc chọn môn khác.",
        )
    required_periods = int(requirement.periods_per_week)
    required_mode = requirement.block_mode or "free"
    if periods == required_periods and mode == required_mode:
        return
    grade = db.get(Grade, school_class.grade_id) if school_class.grade_id else None
    raise HTTPException(
        409,
        f"{school_class.name} – {subject.name} phải khớp chương trình "
        f"{grade.name if grade else 'khối'}: {required_periods} tiết/tuần · "
        f"{block_mode_text(required_mode)}. Dữ liệu đang nhập là "
        f"{periods} tiết/tuần · {block_mode_text(mode)}.",
    )


def grade_requirement_extra_assignments(
    db: Session,
    project: Project,
    grade_id: int,
    classes: list[SchoolClass] | None = None,
    configs: list[tuple[int, int, str]] | None = None,
) -> list[dict]:
    """Return assignments whose subjects are outside a configured target grade.

    ``configs`` can be supplied while editing a grade so the comparison is made
    against the proposed curriculum instead of the rows currently persisted in
    the database. An empty target curriculum is treated as not configured, so it
    does not make existing assignments extra.
    """
    if configs is None:
        requirements = db.scalars(
            select(GradeSubjectRequirement).where(
                GradeSubjectRequirement.project_id == project.id,
                GradeSubjectRequirement.grade_id == grade_id,
            )
        ).all()
        if not requirements:
            return []
        wanted_subject_ids = {row.subject_id for row in requirements}
    else:
        if not configs:
            return []
        wanted_subject_ids = {subject_id for subject_id, _, _ in configs}

    if classes is None:
        classes = db.scalars(
            select(SchoolClass).where(
                SchoolClass.project_id == project.id,
                SchoolClass.grade_id == grade_id,
            )
        ).all()
    if not classes:
        return []

    class_by_id = {row.id: row for row in classes}
    assignments = db.scalars(
        select(Assignment).where(
            Assignment.project_id == project.id,
            Assignment.class_id.in_(list(class_by_id)),
        )
    ).all()
    extras = [row for row in assignments if row.subject_id not in wanted_subject_ids]
    if not extras:
        return []
    subject_ids = {row.subject_id for row in extras}
    subjects = {
        row.id: row
        for row in db.scalars(
            select(Subject).where(
                Subject.project_id == project.id,
                Subject.id.in_(subject_ids),
            )
        ).all()
    }
    return [
        {
            "assignment_id": row.id,
            "class_id": row.class_id,
            "class_name": class_by_id[row.class_id].name,
            "subject_id": row.subject_id,
            "subject_name": subjects.get(row.subject_id).name
            if subjects.get(row.subject_id)
            else f"môn #{row.subject_id}",
            "assigned_periods": int(row.periods_per_week),
            "assigned_mode": row.block_mode or "free",
        }
        for row in extras
    ]


def grade_requirement_missing_assignments(
    db: Session,
    project: Project,
    grade_id: int,
    configs: list[tuple[int, int, str]],
    classes: list[SchoolClass] | None = None,
) -> list[str]:
    """Trả về các môn bắt buộc chưa có phân công cho từng lớp.

    Các phân công đã tồn tại nhưng khác số tiết/chế độ sẽ được đồng bộ nguyên tử
    bởi ``sync_assignments_to_grade_requirements``. Chỉ trường hợp chưa có
    phân công mới cần người dùng chọn giáo viên trước.
    """
    if classes is None:
        classes = db.scalars(
            select(SchoolClass).where(
                SchoolClass.project_id == project.id,
                SchoolClass.grade_id == grade_id,
            )
        ).all()
    if not classes or not configs:
        return []
    class_ids = [row.id for row in classes]
    subject_ids = [subject_id for subject_id, _, _ in configs]
    assignments = db.scalars(
        select(Assignment).where(
            Assignment.project_id == project.id,
            Assignment.class_id.in_(class_ids),
            Assignment.subject_id.in_(subject_ids),
        )
    ).all()
    assigned_pairs = {(row.class_id, row.subject_id) for row in assignments}
    subjects = {
        row.id: row
        for row in db.scalars(
            select(Subject).where(
                Subject.project_id == project.id,
                Subject.id.in_(subject_ids),
            )
        ).all()
    }
    issues: list[str] = []
    for school_class in classes:
        for subject_id, required_periods, required_mode in configs:
            if (school_class.id, subject_id) in assigned_pairs:
                continue
            subject = subjects.get(subject_id)
            subject_name = subject.name if subject else f"môn #{subject_id}"
            issues.append(
                f"{school_class.name} – {subject_name}: thiếu phân công "
                f"{required_periods} tiết/tuần · {block_mode_text(required_mode)}"
            )
    return issues


def sync_assignments_to_grade_requirements(
    db: Session,
    project: Project,
    grade_id: int,
    configs: list[tuple[int, int, str]],
    classes: list[SchoolClass] | None = None,
    displaced_lesson_ids: list[int] | None = None,
) -> int:
    """Đồng bộ phân công hiện có với chương trình khối trong cùng transaction.

    Hàm không tự tạo phân công vì không thể tự chọn giáo viên. Các thay đổi tải
    dạy/tải học được kiểm tra theo tổng delta trước khi sửa ORM objects; các
    ghim và tính khả thi của lịch hiện tại cũng được kiểm tra trước khi commit.
    """
    if classes is None:
        classes = db.scalars(
            select(SchoolClass).where(
                SchoolClass.project_id == project.id,
                SchoolClass.grade_id == grade_id,
            )
        ).all()
    if not classes or not configs:
        return 0

    class_by_id = {row.id: row for row in classes}
    class_ids = list(class_by_id)
    config_by_subject = {
        subject_id: (int(periods), mode or "free")
        for subject_id, periods, mode in configs
    }
    subject_ids = list(config_by_subject)
    assignments = db.scalars(
        select(Assignment).where(
            Assignment.project_id == project.id,
            Assignment.class_id.in_(class_ids),
            Assignment.subject_id.in_(subject_ids),
        )
    ).all()
    if not assignments:
        return 0

    subjects = {
        row.id: row
        for row in db.scalars(
            select(Subject).where(
                Subject.project_id == project.id,
                Subject.id.in_(subject_ids),
            )
        ).all()
    }
    teacher_ids = {row.teacher_id for row in assignments}
    teachers = {
        row.id: row
        for row in db.scalars(
            select(Teacher).where(
                Teacher.project_id == project.id,
                Teacher.id.in_(teacher_ids),
            )
        ).all()
    }

    changes = []
    teacher_deltas: Counter[int] = Counter()
    class_deltas: Counter[int] = Counter()
    for assignment in assignments:
        desired = config_by_subject.get(assignment.subject_id)
        if desired is None:
            continue
        periods, mode = desired
        old_periods = int(assignment.periods_per_week)
        old_mode = assignment.block_mode or "free"
        if old_periods == periods and old_mode == mode:
            continue

        school_class = class_by_id.get(assignment.class_id)
        subject = subjects.get(assignment.subject_id)
        teacher = teachers.get(assignment.teacher_id)
        if not school_class or not subject or not teacher:
            raise HTTPException(
                409,
                "Không thể đồng bộ chương trình khối vì có phân công tham chiếu dữ liệu không còn tồn tại.",
            )

        lessons = db.scalars(
            select(Lesson).where(Lesson.assignment_id == assignment.id)
        ).all()
        scheduled = len(lessons)
        if periods < scheduled and not (
            old_mode == "required_double" and mode == "required_double"
        ):
            raise HTTPException(
                409,
                f"Không thể đổi chương trình: {school_class.name} – {subject.name} "
                f"đang có {scheduled} tiết trên lịch nhưng chuẩn mới chỉ còn {periods} tiết/tuần. "
                "Hãy gỡ bớt tiết trên lịch trước.",
            )

        ensure_assignment_hard_feasible(
            project, teacher, school_class, subject, periods, mode
        )
        delta = periods - old_periods
        teacher_deltas[teacher.id] += delta
        class_deltas[school_class.id] += delta
        changes.append(
            (
                assignment,
                school_class,
                subject,
                teacher,
                lessons,
                periods,
                mode,
                old_periods,
                old_mode,
            )
        )

    for teacher_id, delta in teacher_deltas.items():
        teacher = teachers[teacher_id]
        ensure_teacher_load_fits(
            db,
            project,
            teacher,
            teacher_assigned_periods(db, project.id, teacher_id) + delta,
        )
    for class_id, delta in class_deltas.items():
        school_class = class_by_id[class_id]
        ensure_class_load_fits(
            project,
            school_class,
            class_assigned_periods(db, project.id, class_id) + delta,
        )

    for (
        assignment,
        school_class,
        subject,
        _teacher,
        lessons,
        periods,
        mode,
        old_periods,
        old_mode,
    ) in changes:
        periods_changed = periods != old_periods
        mode_changed = mode != old_mode
        assignment.periods_per_week = periods
        assignment.block_mode = mode
        assignment.consecutive_pattern = ""

        if mode_changed or (periods_changed and assignment_requires_double(assignment)):
            original_lesson_ids = {lesson.id for lesson in lessons}
            lessons, block_error = reconcile_assignment_lesson_blocks(
                db, project, assignment, lessons, old_mode=old_mode
            )
            if displaced_lesson_ids is not None:
                displaced_lesson_ids.extend(
                    sorted(original_lesson_ids - {lesson.id for lesson in lessons})
                )
            if block_error:
                raise HTTPException(
                    409,
                    f"Không thể đổi chương trình cho {school_class.name} – {subject.name}: {block_error}",
                )
            fixed_error = normalize_assignment_fixed_rows(
                db, project, assignment, lessons
            )
            if fixed_error:
                raise HTTPException(
                    409,
                    f"Không thể đổi chương trình cho {school_class.name} – {subject.name}: {fixed_error}",
                )
            if not assignment_completion_feasible(
                db, project, assignment, [lesson.slot for lesson in lessons]
            ):
                raise HTTPException(
                    409,
                    f"Không thể đổi chương trình cho {school_class.name} – {subject.name} vì "
                    "các tiết hiện có không thể hoàn thành hợp lệ theo chế độ mới và các ràng buộc hiện tại.",
                )

    return len(changes)


__all__ = [name for name in globals() if not name.startswith("__")]
