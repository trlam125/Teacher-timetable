from __future__ import annotations

from app.services.foundation import *
from app.services.web import *
from app.services.auth import *
from app.services.schedule_service import *
from app.services.entities import *

def ensure_school_for_name(db: Session, school_name: str) -> School:
    clean_name = bounded_text(school_name, "Tên trường", 200)
    school = db.scalar(select(School).where(School.name == clean_name))
    if school is None:
        school = School(name=clean_name)
        db.add(school)
        db.flush()
    return school

def get_project(pid: int, user: User, db: Session) -> Project:
    if not is_admin(user):
        raise HTTPException(403, "Chỉ quản trị viên được thực hiện thao tác này")
    p = db.get(Project, pid)
    if not p or not user_can_access_school(user, p.school_id, db):
        raise HTTPException(404, "Không tìm thấy bộ thời khóa biểu")
    return p

def chatbot_ui_context(project: Project | None) -> dict:
    return {
        "chatbot_project_id": project.id if project else None,
        "chatbot_project_name": project.name if project else "",
        "chatbot_enabled": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "chatbot_primary_model": os.getenv("GEMINI_MODEL", "gemini-3.7-flash").strip()
        or "gemini-3.7-flash",
    }

def chatbot_project_for_user(
    user: User, db: Session, preferred_id: int | None = None
) -> Project | None:
    if preferred_id is not None:
        if is_admin(user):
            return get_project(preferred_id, user, db)
        if user.role == "teacher":
            project = db.get(Project, preferred_id)
            if project and user_can_access_school(user, project.school_id, db):
                return project
            return None
        return None
    if is_admin(user) or user.role == "teacher":
        query = select(Project)
        if not is_super_admin(user):
            school_ids = user_school_ids(user, db)
            if not school_ids:
                return None
            query = query.where(Project.school_id.in_(school_ids))
        return db.scalar(query.order_by(Project.id.desc()).limit(1))
    return None

def chatbot_project_data_for_user(
    pid: int, user: User, db: Session
) -> tuple[Project, dict]:
    if is_admin(user):
        project = get_project(pid, user, db)
        return project, project_data(db, project)
    if user.role == "teacher":
        project = db.get(Project, pid)
        if not project or not user_can_access_school(user, project.school_id, db):
            raise HTTPException(404, "Không tìm thấy bộ thời khóa biểu")
        return project, public_project_data(db, project)
    raise HTTPException(
        403, "Tài khoản không có quyền sử dụng chatbot cho bộ thời khóa biểu này"
    )

def get_project_for_update(pid: int, user: User, db: Session) -> Project:
    """Khóa project đến hết transaction để tuần tự hóa mọi thay đổi lịch."""
    if not is_admin(user):
        raise HTTPException(403, "Chỉ quản trị viên được thực hiện thao tác này")
    query = select(Project).where(Project.id == pid)
    if not is_super_admin(user):
        school_ids = user_school_ids(user, db)
        if not school_ids:
            raise HTTPException(404, "Không tìm thấy bộ thời khóa biểu")
        query = query.where(Project.school_id.in_(school_ids))
    project = db.scalar(query.with_for_update())
    if not project:
        raise HTTPException(404, "Không tìm thấy bộ thời khóa biểu")
    return project

def validate_clone_source(db: Session, pid: int) -> dict[str, list]:
    """Kiểm tra các tham chiếu nội bộ trước khi nhân bản project.

    Clone phải là thao tác all-or-nothing: nếu dữ liệu nguồn có tham chiếu chéo
    project hoặc dữ liệu legacy bị mồ côi thì dừng bằng HTTP 409, thay vì tạo
    một bản sao thiếu dữ liệu hoặc phát sinh KeyError/500 giữa transaction.
    """
    rows = {
        "departments": db.scalars(
            select(Department).where(Department.project_id == pid)
        ).all(),
        "subjects": db.scalars(select(Subject).where(Subject.project_id == pid)).all(),
        "teachers": db.scalars(select(Teacher).where(Teacher.project_id == pid)).all(),
        "teacher_subjects": db.scalars(
            select(TeacherSubject).where(TeacherSubject.project_id == pid)
        ).all(),
        "grades": db.scalars(select(Grade).where(Grade.project_id == pid)).all(),
        "grade_requirements": db.scalars(
            select(GradeSubjectRequirement).where(
                GradeSubjectRequirement.project_id == pid
            )
        ).all(),
        "classes": db.scalars(
            select(SchoolClass).where(SchoolClass.project_id == pid)
        ).all(),
        "assignments": db.scalars(
            select(Assignment).where(Assignment.project_id == pid)
        ).all(),
        "fixed_lessons": db.scalars(
            select(FixedLesson).where(FixedLesson.project_id == pid)
        ).all(),
        "lessons": db.scalars(select(Lesson).where(Lesson.project_id == pid)).all(),
    }

    department_ids = {row.id for row in rows["departments"]}
    subject_ids = {row.id for row in rows["subjects"]}
    teacher_ids = {row.id for row in rows["teachers"]}
    grade_ids = {row.id for row in rows["grades"]}
    class_ids = {row.id for row in rows["classes"]}
    assignment_ids = {row.id for row in rows["assignments"]}
    errors = []

    invalid_teacher_ids = [
        row.id
        for row in rows["teachers"]
        if row.department_id is not None and row.department_id not in department_ids
    ]
    if invalid_teacher_ids:
        errors.append(f"giáo viên có tổ chuyên môn không hợp lệ: {invalid_teacher_ids}")

    invalid_teacher_subject_ids = [
        row.id
        for row in rows["teacher_subjects"]
        if row.teacher_id not in teacher_ids or row.subject_id not in subject_ids
    ]
    if invalid_teacher_subject_ids:
        errors.append(
            f"quan hệ giáo viên-môn học không hợp lệ: {invalid_teacher_subject_ids}"
        )

    invalid_requirement_ids = [
        row.id
        for row in rows["grade_requirements"]
        if row.grade_id not in grade_ids or row.subject_id not in subject_ids
    ]
    if invalid_requirement_ids:
        errors.append(f"chương trình khối không hợp lệ: {invalid_requirement_ids}")

    invalid_class_ids = [
        row.id
        for row in rows["classes"]
        if row.grade_id is not None and row.grade_id not in grade_ids
    ]
    if invalid_class_ids:
        errors.append(f"lớp có khối không hợp lệ: {invalid_class_ids}")

    invalid_assignment_ids = [
        row.id
        for row in rows["assignments"]
        if row.class_id not in class_ids
        or row.subject_id not in subject_ids
        or row.teacher_id not in teacher_ids
    ]
    if invalid_assignment_ids:
        errors.append(f"phân công không hợp lệ: {invalid_assignment_ids}")

    invalid_fixed_lesson_ids = [
        row.id
        for row in rows["fixed_lessons"]
        if row.assignment_id not in assignment_ids
    ]
    if invalid_fixed_lesson_ids:
        errors.append(f"tiết cố định không hợp lệ: {invalid_fixed_lesson_ids}")

    invalid_lesson_ids = [
        row.id for row in rows["lessons"] if row.assignment_id not in assignment_ids
    ]
    if invalid_lesson_ids:
        errors.append(f"tiết học không hợp lệ: {invalid_lesson_ids}")

    if errors:
        raise HTTPException(
            409,
            "Không thể nhân bản vì project nguồn có dữ liệu không hợp lệ: "
            + " | ".join(errors),
        )
    return rows

def teacher_view_projects(user: User, db: Session) -> list[Project]:
    if user.role != "teacher":
        raise HTTPException(403, "Tài khoản giáo viên không hợp lệ")
    school_ids = user_school_ids(user, db)
    if not school_ids:
        return []
    return db.scalars(
        select(Project)
        .where(Project.school_id.in_(school_ids))
        .order_by(Project.id.desc())
    ).all()

def teacher_view_project(
    user: User, db: Session, project_id: Optional[int] = None
) -> Project | None:
    projects = teacher_view_projects(user, db)
    if not projects:
        return None
    if project_id is None:
        return projects[0]
    for project in projects:
        if project.id == project_id:
            return project
    raise HTTPException(404, "Không tìm thấy bộ thời khóa biểu")

def project_lessons_data(db: Session, project_id: int):
    project = db.get(Project, project_id)
    fixed_slots = fixed_coverage_slots(db, project) if project else {}
    return [
        {
            "id": row.id,
            "assignment_id": row.assignment_id,
            "slot": row.slot,
            "block_id": row.block_id,
            "block_size": row.block_size,
            "locked": bool(
                row.locked
                or row.slot in fixed_slots.get(row.assignment_id, set())
            ),
        }
        for row in db.scalars(
            select(Lesson).where(Lesson.project_id == project_id)
        ).all()
    ]

def project_data(db: Session, p: Project):
    deps = db.scalars(select(Department).where(Department.project_id == p.id)).all()
    subs = db.scalars(select(Subject).where(Subject.project_id == p.id)).all()
    teas = db.scalars(select(Teacher).where(Teacher.project_id == p.id)).all()
    grades = db.scalars(select(Grade).where(Grade.project_id == p.id)).all()
    grade_requirements = db.scalars(
        select(GradeSubjectRequirement).where(
            GradeSubjectRequirement.project_id == p.id
        )
    ).all()
    classes = db.scalars(
        select(SchoolClass).where(SchoolClass.project_id == p.id)
    ).all()
    assignments = db.scalars(
        select(Assignment).where(Assignment.project_id == p.id)
    ).all()
    lessons = db.scalars(select(Lesson).where(Lesson.project_id == p.id)).all()
    fixed_slots = fixed_coverage_slots(db, p)
    sm = {x.id: x for x in subs}
    tm = {x.id: x for x in teas}
    cm = {x.id: x for x in classes}
    teacher_subject_rows = db.scalars(
        select(TeacherSubject).where(TeacherSubject.project_id == p.id)
    ).all()
    teacher_subject_map = defaultdict(list)
    for row in teacher_subject_rows:
        teacher_subject_map[row.teacher_id].append(row.subject_id)
    teacher_loads = Counter()
    for assignment in assignments:
        teacher_loads[assignment.teacher_id] += assignment.periods_per_week
    capacity_issues = schedule_teacher_capacity_issues(db, p, assignments)
    class_capacity_issues = schedule_class_capacity_issues(p, classes, assignments)
    duplicate_issues = duplicate_assignment_issues(db, assignments)
    assigned_teacher_ids = {x.teacher_id for x in assignments}
    assigned_subject_ids = {x.subject_id for x in assignments}
    assigned_class_ids = {x.class_id for x in assignments}
    return {
        "project": {
            "id": p.id,
            "name": p.name,
            "school_name": p.school_name,
            "days": p.days,
            "sessions": p.sessions,
            "periods": p.periods_per_session,
            "share_token": p.share_token,
            "blocked_slots": valid_slots(
                p, parse_slots(p.blocked_slots_json), strict=False
            ),
        },
        "departments": [{"id": x.id, "name": x.name} for x in deps],
        "subjects": [
            {
                "id": x.id,
                "name": x.name,
                "short_name": x.short_name,
                "max_consecutive": x.max_consecutive,
            }
            for x in subs
        ],
        "teachers": [
            {
                "id": x.id,
                "name": x.name,
                "short_name": x.short_name,
                "department_id": x.department_id,
                "max_periods_day": x.max_periods_day,
                "unavailable": list(parse_slots(x.unavailable_json)),
                "subject_ids": sorted(teacher_subject_map.get(x.id, [])),
                "assigned_periods": teacher_loads.get(x.id, 0),
                "week_capacity": teacher_week_capacity(p, x),
            }
            for x in teas
        ],
        "grades": [{"id": x.id, "name": x.name} for x in grades],
        "grade_requirements": [
            {
                "id": x.id,
                "grade_id": x.grade_id,
                "subject_id": x.subject_id,
                "periods_per_week": x.periods_per_week,
                "block_mode": x.block_mode,
            }
            for x in grade_requirements
        ],
        "classes": [
            {
                "id": x.id,
                "name": x.name,
                "grade_id": x.grade_id,
                "unavailable": list(parse_slots(x.unavailable_json)),
            }
            for x in classes
        ],
        "assignments": [
            {
                "id": x.id,
                "class_id": x.class_id,
                "subject_id": x.subject_id,
                "teacher_id": x.teacher_id,
                "periods_per_week": x.periods_per_week,
                "block_mode": x.block_mode,
                "class_name": cm.get(x.class_id).name if cm.get(x.class_id) else "?",
                "subject_name": sm.get(x.subject_id).name
                if sm.get(x.subject_id)
                else "?",
                "subject_short": sm.get(x.subject_id).short_name
                if sm.get(x.subject_id)
                else "?",
                "teacher_name": tm.get(x.teacher_id).name
                if tm.get(x.teacher_id)
                else "?",
                "teacher_short": tm.get(x.teacher_id).short_name
                if tm.get(x.teacher_id)
                else "?",
            }
            for x in assignments
        ],
        "lessons": [
            {
                "id": x.id,
                "assignment_id": x.assignment_id,
                "slot": x.slot,
                "block_id": x.block_id,
                "block_size": x.block_size,
                "locked": bool(
                    x.locked
                    or x.slot in fixed_slots.get(x.assignment_id, set())
                ),
            }
            for x in lessons
        ],
        "schedule_validation": schedule_ui_validation_report(db, p),
        "coverage": {
            "duplicate_assignments": duplicate_issues,
            "over_capacity_teachers": capacity_issues,
            "over_capacity_classes": class_capacity_issues,
            "unassigned_teachers": [
                {"id": x.id, "name": x.name}
                for x in teas
                if x.id not in assigned_teacher_ids
            ],
            "unassigned_subjects": [
                {"id": x.id, "name": x.name}
                for x in subs
                if x.id not in assigned_subject_ids
            ],
            "unassigned_classes": [
                {"id": x.id, "name": x.name}
                for x in classes
                if x.id not in assigned_class_ids
            ],
        },
    }

def public_project_data(db: Session, p: Project):
    subjects = {
        x.id: x
        for x in db.scalars(select(Subject).where(Subject.project_id == p.id)).all()
    }
    teachers = {
        x.id: x
        for x in db.scalars(select(Teacher).where(Teacher.project_id == p.id)).all()
    }
    classes = {
        x.id: x
        for x in db.scalars(
            select(SchoolClass).where(SchoolClass.project_id == p.id)
        ).all()
    }
    assignments = db.scalars(
        select(Assignment).where(Assignment.project_id == p.id)
    ).all()
    lessons = db.scalars(select(Lesson).where(Lesson.project_id == p.id)).all()
    return {
        "project": {
            "id": p.id,
            "name": p.name,
            "school_name": p.school_name,
            "days": p.days,
            "sessions": p.sessions,
            "periods": p.periods_per_session,
            "blocked_slots": valid_slots(
                p, parse_slots(p.blocked_slots_json), strict=False
            ),
        },
        "classes": [{"id": item.id, "name": item.name} for item in classes.values()],
        "teachers": [
            {"id": item.id, "name": item.name, "short_name": item.short_name}
            for item in teachers.values()
        ],
        "subjects": [
            {"id": item.id, "name": item.name, "short_name": item.short_name}
            for item in subjects.values()
        ],
        "assignments": [
            {
                "id": item.id,
                "class_id": item.class_id,
                "subject_id": item.subject_id,
                "teacher_id": item.teacher_id,
                "periods_per_week": item.periods_per_week,
                "block_mode": item.block_mode,
                "class_name": classes[item.class_id].name
                if item.class_id in classes
                else "?",
                "subject_name": subjects[item.subject_id].name
                if item.subject_id in subjects
                else "?",
                "subject_short": subjects[item.subject_id].short_name
                if item.subject_id in subjects
                else "?",
                "teacher_name": teachers[item.teacher_id].name
                if item.teacher_id in teachers
                else "?",
                "teacher_short": teachers[item.teacher_id].short_name
                if item.teacher_id in teachers
                else "?",
            }
            for item in assignments
        ],
        "lessons": [
            {"id": item.id, "assignment_id": item.assignment_id, "slot": item.slot, "block_id": item.block_id, "block_size": item.block_size}
            for item in lessons
        ],
    }


__all__ = [name for name in globals() if not name.startswith('__')]
