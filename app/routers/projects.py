from __future__ import annotations

from fastapi import APIRouter
from app.services.runtime import *

router = APIRouter()

@router.get("/projects", response_class=HTMLResponse)
def projects(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if user.role == "teacher":
        return RedirectResponse("/teacher", 303)
    if not is_admin(user):
        return RedirectResponse("/logout", 303)
    project_query = select(Project)
    assigned_schools = user_schools(user, db)
    if not is_super_admin(user):
        school_ids = {school.id for school in assigned_schools}
        if school_ids:
            project_query = project_query.where(Project.school_id.in_(school_ids))
        else:
            project_query = project_query.where(Project.id == -1)
    rows = db.scalars(project_query.order_by(Project.id.desc())).all()
    return templates.TemplateResponse(
        "projects.html",
        {
            "request": request,
            "user": user,
            "greeting_name": user_greeting_name(user),
            "projects": rows,
            "assigned_schools": assigned_schools,
            **chatbot_ui_context(rows[0] if rows else None),
        },
    )

@router.post("/projects")
def create_project(
    name: str = Form(""),
    school_name: str = Form(""),
    school_id: Optional[str] = Form(None),
    days: str = Form("6"),
    sessions: str = Form("2"),
    periods: str = Form("5"),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_admin(user):
        raise HTTPException(403)
    try:
        clean_name = bounded_text(name, "Tên bộ thời khóa biểu", 200)
    except HTTPException as exc:
        return redirect_with_notice(
            "/projects", str(exc.detail), open_create=1
        )

    if school_id not in (None, ""):
        try:
            parsed_school_id = int(school_id)
        except (TypeError, ValueError):
            return redirect_with_notice(
                "/projects", "Trường được chọn không hợp lệ", open_create=1
            )
        school = db.get(School, parsed_school_id)
        if not school or not user_can_access_school(user, school.id, db):
            return redirect_with_notice(
                "/projects",
                "Bạn không có quyền tạo thời khóa biểu cho trường này",
                open_create=1,
            )
        clean_school_name = school.name
    elif is_super_admin(user) and school_name.strip():
        # Giữ tương thích với form/client cũ; giao diện hiện tại tạo trường tại
        # Quản lý tài khoản rồi chọn trường khi tạo thời khóa biểu.
        school = ensure_school_for_name(db, school_name.strip())
        clean_school_name = school.name
    else:
        return redirect_with_notice(
            "/projects",
            "Tài khoản chưa được gán trường để tạo thời khóa biểu",
            open_create=1,
        )

    try:
        validated_days = bounded_int(days, 6, 5, 7, "Số ngày học")
        validated_sessions = bounded_int(sessions, 2, 1, 2, "Số buổi mỗi ngày")
        validated_periods = bounded_int(periods, 5, 1, 8, "Số tiết mỗi buổi")
    except HTTPException as exc:
        return redirect_with_notice(
            "/projects", str(exc.detail), open_create=1
        )
    p = Project(
        owner_id=user.id,
        school_id=school.id,
        name=clean_name,
        school_name=clean_school_name,
        days=validated_days,
        sessions=validated_sessions,
        periods_per_session=validated_periods,
    )
    db.add(p)
    db.commit()
    return RedirectResponse(f"/projects/{p.id}", 303)

@router.post("/projects/{pid}/rename")
def rename_project(
    pid: int,
    name: str = Form(""),
    return_to: str = Form("projects"),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    destination = f"/projects/{pid}" if return_to == "workspace" else "/projects"
    try:
        clean_name = bounded_text(name, "Tên bộ thời khóa biểu", 200)
    except HTTPException as exc:
        extra = {"open_rename": 1}
        if destination == "/projects":
            extra["rename_project_id"] = pid
        return redirect_with_notice(
            destination,
            str(exc.detail),
            **extra,
        )

    if project.name == clean_name:
        return redirect_with_notice(
            destination,
            "Tên bộ thời khóa biểu không thay đổi",
            kind="info",
        )

    project.name = clean_name
    db.commit()
    return redirect_with_notice(
        destination,
        "Đã đổi tên bộ thời khóa biểu",
        kind="success",
    )

@router.post("/projects/{pid}/clone")
def clone_project(
    pid: int,
    name: str | None = Form(None),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    # Dùng cùng khóa với mọi API chỉnh sửa để bản sao luôn được đọc từ một
    # trạng thái nhất quán, không trộn dữ liệu trước và sau một thay đổi đồng thời.
    src = get_project_for_update(pid, user, db)
    rows = validate_clone_source(db, pid)

    suffix = " (bản sao)"
    if name is None:
        clone_name = src.name[: 200 - len(suffix)] + suffix
    else:
        clone_name = name.strip()
        if not clone_name:
            raise HTTPException(400, "Tên bộ thời khóa biểu không được để trống")
        if len(clone_name) > 200:
            raise HTTPException(
                400, "Tên bộ thời khóa biểu không được vượt quá 200 ký tự"
            )

    p = Project(
        owner_id=user.id,
        school_id=src.school_id,
        name=clone_name,
        school_name=src.school_name,
        days=src.days,
        sessions=src.sessions,
        periods_per_session=src.periods_per_session,
        blocked_slots_json=src.blocked_slots_json,
    )
    db.add(p)
    db.flush()

    maps = {"dep": {}, "sub": {}, "tea": {}, "grade": {}, "cls": {}, "ass": {}}
    for x in rows["departments"]:
        n = Department(project_id=p.id, name=x.name)
        db.add(n)
        db.flush()
        maps["dep"][x.id] = n.id
    for x in rows["subjects"]:
        n = Subject(
            project_id=p.id,
            name=x.name,
            short_name=x.short_name,
            max_consecutive=x.max_consecutive,
        )
        db.add(n)
        db.flush()
        maps["sub"][x.id] = n.id
    for x in rows["teachers"]:
        n = Teacher(
            project_id=p.id,
            department_id=maps["dep"].get(x.department_id),
            name=x.name,
            short_name=x.short_name,
            max_periods_day=x.max_periods_day,
            unavailable_json=x.unavailable_json,
        )
        db.add(n)
        db.flush()
        maps["tea"][x.id] = n.id
    # Tài khoản giáo viên là người xem toàn cục nên project bản sao tự động
    # xuất hiện trong cổng giáo viên; không còn khái niệm sao chép quyền liên kết.
    for x in rows["teacher_subjects"]:
        db.add(
            TeacherSubject(
                project_id=p.id,
                teacher_id=maps["tea"][x.teacher_id],
                subject_id=maps["sub"][x.subject_id],
            )
        )
    # Nguyện vọng là lịch sử tham khảo nên không sao chép sang project mới.
    for x in rows["grades"]:
        n = Grade(project_id=p.id, name=x.name)
        db.add(n)
        db.flush()
        maps["grade"][x.id] = n.id
    for x in rows["grade_requirements"]:
        db.add(
            GradeSubjectRequirement(
                project_id=p.id,
                grade_id=maps["grade"][x.grade_id],
                subject_id=maps["sub"][x.subject_id],
                periods_per_week=x.periods_per_week,
                block_mode=x.block_mode,
            )
        )
    for x in rows["classes"]:
        n = SchoolClass(
            project_id=p.id,
            grade_id=maps["grade"].get(x.grade_id),
            name=x.name,
            unavailable_json=x.unavailable_json,
        )
        db.add(n)
        db.flush()
        maps["cls"][x.id] = n.id
    for x in rows["assignments"]:
        n = Assignment(
            project_id=p.id,
            class_id=maps["cls"][x.class_id],
            subject_id=maps["sub"][x.subject_id],
            teacher_id=maps["tea"][x.teacher_id],
            periods_per_week=x.periods_per_week,
            block_mode=x.block_mode,
            consecutive_pattern="",
        )
        db.add(n)
        db.flush()
        maps["ass"][x.id] = n.id
    for x in rows["fixed_lessons"]:
        db.add(
            FixedLesson(
                project_id=p.id,
                assignment_id=maps["ass"][x.assignment_id],
                slot=x.slot,
                group_size=x.group_size,
            )
        )
    cloned_block_ids = {}
    for x in rows["lessons"]:
        source_block = x.block_id or f"legacy:{x.id}"
        block_key = (x.assignment_id, source_block)
        cloned_block_id = cloned_block_ids.setdefault(
            block_key, new_schedule_block_id()
        )
        db.add(
            Lesson(
                project_id=p.id,
                assignment_id=maps["ass"][x.assignment_id],
                slot=x.slot,
                block_id=cloned_block_id,
                block_size=int(getattr(x, "block_size", 1) or 1),
                locked=x.locked,
            )
        )
    db.commit()
    return RedirectResponse(f"/projects/{p.id}", 303)

@router.post("/projects/{pid}/delete")
def delete_project(
    pid: int, user: User = Depends(current_user), db: Session = Depends(db_session)
):
    project = get_project_for_update(pid, user, db)

    # Xóa theo thứ tự phụ thuộc khóa ngoại để toàn bộ dữ liệu của bộ TKB
    # được dọn sạch trong cùng một transaction.
    for model in (
        Lesson,
        FixedLesson,
        TeacherSubject,
        GradeSubjectRequirement,
        Assignment,
        TeacherPreference,
        SchoolClass,
        Teacher,
        Subject,
        Grade,
        Department,
    ):
        db.execute(delete(model).where(model.project_id == pid))

    # Log chatbot không có khóa ngoại tới projects, nhưng vẫn dọn theo project
    # để không giữ lại dữ liệu mồ côi sau khi bộ TKB đã bị xóa.
    db.execute(delete(ChatbotErrorLog).where(ChatbotErrorLog.project_id == pid))
    db.delete(project)
    db.commit()
    return RedirectResponse("/projects", 303)

@router.get("/projects/{pid}", response_class=HTMLResponse)
def project_page(
    pid: int,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    p = get_project(pid, user, db)
    data = project_data(db, p)
    return templates.TemplateResponse(
        "workspace.html",
        {
            "request": request,
            "user": user,
            "p": p,
            "data": data,
            "days": DAYS,
            "public_base_url": public_base_url(request)
            or str(request.base_url).rstrip("/"),
            **chatbot_ui_context(p),
        },
    )

