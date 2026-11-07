from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import (
    Depends,
    Form,
    HTTPException,
    Request,
)
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    Assignment,
    ChatbotErrorLog,
    Department,
    FixedLesson,
    Grade,
    GradeSubjectRequirement,
    Lesson,
    Project,
    School,
    SchoolClass,
    Subject,
    Teacher,
    TeacherPreference,
    TeacherSubject,
    User,
)
from app.scheduling.rules import bounded_int
from app.services.authentication.permissions import (
    is_admin,
    is_super_admin,
    user_can_access_school,
    user_greeting_name,
    user_schools,
)
from app.services.authentication.sessions import current_user, db_session, public_base_url
from app.services.projects import (
    chatbot_ui_context,
    ensure_school_for_name,
    get_project,
    get_project_for_update,
    project_data,
    validate_clone_source,
)
from app.services.schedule_operations.blocks import new_schedule_block_id
from app.services.web import bounded_text, redirect_with_notice, templates
from app.settings import DAYS

router = APIRouter()


@router.get("/projects", response_class=HTMLResponse)
@router.get("/projects/trash", response_class=HTMLResponse)
def projects(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if user.role == "teacher":
        return RedirectResponse("/teacher", 303)
    if not is_admin(user):
        return RedirectResponse("/logout", 303)
    in_trash = request.url.path == "/projects/trash"
    project_query = select(Project).where(
        Project.deleted_at.is_not(None) if in_trash else Project.deleted_at.is_(None)
    )
    assigned_schools = user_schools(user, db)
    if not is_super_admin(user):
        school_ids = {school.id for school in assigned_schools}
        if school_ids:
            project_query = project_query.where(Project.school_id.in_(school_ids))
        else:
            project_query = project_query.where(Project.id == -1)
    ordering = (
        (Project.deleted_at.desc(), Project.id.desc()) if in_trash else (Project.id.desc(),)
    )
    rows = db.scalars(project_query.order_by(*ordering)).all()
    return templates.TemplateResponse(
        "projects.html",
        {
            "request": request,
            "user": user,
            "greeting_name": user_greeting_name(user),
            "projects": rows,
            "assigned_schools": assigned_schools,
            "in_trash": in_trash,
            **chatbot_ui_context(rows[0] if rows and not in_trash else None),
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
        return redirect_with_notice("/projects", str(exc.detail), open_create=1)

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
        return redirect_with_notice("/projects", str(exc.detail), open_create=1)
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
    school_id: Optional[str] = Form(None),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project_for_update(pid, user, db)
    destination = f"/projects/{pid}" if return_to == "workspace" else "/projects"
    try:
        clean_name = bounded_text(name, "Tên bộ thời khóa biểu", 200)
        school = None
        if school_id is not None:
            try:
                parsed_school_id = int(school_id)
            except (TypeError, ValueError) as exc:
                raise HTTPException(400, "Hãy chọn trường hợp lệ") from exc
            school = db.get(School, parsed_school_id)
            if school is None or not user_can_access_school(user, school.id, db):
                raise HTTPException(400, "Bạn không có quyền chọn trường này")
        elif project.school_id is not None:
            # Older clients only submit a name; retain their current school.
            school = db.get(School, project.school_id)
    except HTTPException as exc:
        extra = {"open_rename": 1}
        if destination == "/projects":
            extra["rename_project_id"] = pid
        return redirect_with_notice(
            destination,
            str(exc.detail),
            **extra,
        )

    new_school_id = school.id if school is not None else project.school_id
    new_school_name = school.name if school is not None else project.school_name
    school_changed = project.school_id != new_school_id or project.school_name != new_school_name
    if project.name == clean_name and not school_changed:
        return redirect_with_notice(
            destination,
            "Tên và trường của bộ thời khóa biểu không thay đổi",
            kind="info",
        )

    project.name = clean_name
    project.school_id = new_school_id
    project.school_name = new_school_name
    db.commit()
    return redirect_with_notice(
        destination,
        "Đã cập nhật tên và trường của bộ thời khóa biểu" if school_changed else "Đã đổi tên bộ thời khóa biểu",
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
        n = Grade(project_id=p.id, name=x.name, blocked_slots_json=x.blocked_slots_json)
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
    project.deleted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.commit()
    return redirect_with_notice(
        "/projects",
        "Đã chuyển bộ thời khóa biểu vào Thùng rác. Bạn có thể khôi phục bất cứ lúc nào.",
        kind="success",
    )


@router.post("/projects/{pid}/restore")
def restore_project(
    pid: int, user: User = Depends(current_user), db: Session = Depends(db_session)
):
    project = get_project_for_update(pid, user, db, trashed=True)
    project.deleted_at = None
    db.commit()
    return redirect_with_notice("/projects", "Đã khôi phục bộ thời khóa biểu", kind="success")


def _purge_project_rows(db: Session, projects: list[Project]):
    project_ids = [project.id for project in projects]
    # Xóa theo thứ tự phụ thuộc khóa ngoại để toàn bộ dữ liệu của bộ TKB
    # được dọn sạch trong cùng một transaction, kể cả khi làm rỗng thùng rác.
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
        db.execute(delete(model).where(model.project_id.in_(project_ids)))

    # Log chatbot không có khóa ngoại tới projects, nhưng vẫn dọn theo project
    # để không giữ lại dữ liệu mồ côi sau khi bộ TKB đã bị xóa.
    db.execute(delete(ChatbotErrorLog).where(ChatbotErrorLog.project_id.in_(project_ids)))
    for project in projects:
        db.delete(project)


@router.post("/projects/trash/empty")
def empty_project_trash(
    project_ids: list[int] = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_admin(user):
        raise HTTPException(403, "Chỉ quản trị viên được làm rỗng thùng rác")
    ids = set(project_ids)
    query = select(Project).where(Project.id.in_(ids), Project.deleted_at.is_not(None))
    if not is_super_admin(user):
        school_ids = {school.id for school in user_schools(user, db)}
        query = query.where(Project.school_id.in_(school_ids))
    # Delete only the entries shown when confirming. Restored projects and new
    # arrivals must not be silently included in an irreversible bulk deletion.
    rows = db.scalars(query.order_by(Project.id).with_for_update()
                      .execution_options(populate_existing=True)).all()
    if not rows or len(rows) != len(ids):
        return redirect_with_notice(
            "/projects/trash", "Thùng rác đã thay đổi hoặc có mục bạn không được phép xóa. Hãy kiểm tra lại danh sách."
        )
    try:
        _purge_project_rows(db, rows)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return redirect_with_notice(
        "/projects/trash", f"Đã xóa vĩnh viễn {len(rows)} bộ thời khóa biểu trong thùng rác", kind="success"
    )


@router.post("/projects/{pid}/purge")
def purge_project(
    pid: int, user: User = Depends(current_user), db: Session = Depends(db_session)
):
    project = get_project_for_update(pid, user, db, trashed=True)
    try:
        _purge_project_rows(db, [project])
        db.commit()
    except Exception:
        db.rollback()
        raise
    return redirect_with_notice(
        "/projects/trash", "Đã xóa vĩnh viễn bộ thời khóa biểu", kind="success"
    )


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
            "assigned_schools": user_schools(user, db),
            "data": data,
            "days": DAYS,
            "public_base_url": public_base_url(request)
            or str(request.base_url).rstrip("/"),
            **chatbot_ui_context(p),
        },
    )
