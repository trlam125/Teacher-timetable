from __future__ import annotations

from fastapi import APIRouter
from app.services.runtime import *

router = APIRouter()

@router.get("/teacher", response_class=HTMLResponse)
def teacher_portal(
    request: Request,
    project_id: Optional[int] = None,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    teacher_schools = user_schools(user, db)
    projects = teacher_view_projects(user, db)
    if not projects:
        return templates.TemplateResponse(
            "teacher_empty.html",
            {
                "request": request,
                "user": user,
                "teacher_schools": teacher_schools,
            },
        )
    project = teacher_view_project(user, db, project_id)
    preference_history = teacher_own_preference_payload(db, project, user.id)
    current_preference = next(
        (item for item in preference_history if item["status"] == "pending"), None
    )
    return templates.TemplateResponse(
        "teacher_portal.html",
        {
            "request": request,
            "user": user,
            "p": project,
            "data": public_project_data(db, project),
            "days": DAYS,
            "teacher_projects": projects,
            "preference_history": preference_history,
            "current_preference": current_preference,
            "preference_saved": request.query_params.get("preference_saved") == "1",
            **chatbot_ui_context(project),
        },
    )

@router.get("/api/teacher/data")
def api_teacher_data(
    project_id: Optional[int] = None,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = teacher_view_project(user, db, project_id)
    if not project:
        raise HTTPException(404, "Chưa có bộ thời khóa biểu nào")
    return public_project_data(db, project)

@router.get("/teacher/account", response_class=HTMLResponse)
def teacher_account_page(
    request: Request,
    project_id: Optional[int] = None,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if user.role != "teacher":
        raise HTTPException(403, "Tài khoản giáo viên không hợp lệ")
    project = db.get(Project, project_id) if project_id is not None else None
    if project_id is not None and (
        not project or not user_can_access_school(user, project.school_id, db)
    ):
        raise HTTPException(404, "Không tìm thấy bộ thời khóa biểu")
    return templates.TemplateResponse(
        "teacher_account.html",
        {
            "request": request,
            "user": user,
            "p": project,
            "error": None,
            "success": None,
            **chatbot_ui_context(project),
        },
    )

@router.post("/teacher/account/password", response_class=HTMLResponse)
def update_teacher_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    project_id: Optional[int] = Form(None),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if user.role != "teacher":
        raise HTTPException(403, "Tài khoản giáo viên không hợp lệ")
    project = db.get(Project, project_id) if project_id is not None else None
    if project_id is not None and (
        not project or not user_can_access_school(user, project.school_id, db)
    ):
        raise HTTPException(404, "Không tìm thấy bộ thời khóa biểu")
    context = {
        "request": request,
        "user": user,
        "p": project,
        "error": None,
        "success": None,
        **chatbot_ui_context(project),
    }
    if not pwd.verify(current_password, user.password_hash):
        context["error"] = "Mật khẩu hiện tại không đúng."
        return templates.TemplateResponse(
            "teacher_account.html", context, status_code=400
        )
    if len(new_password) < MIN_PASSWORD_LENGTH:
        context["error"] = f"Mật khẩu mới phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự."
        return templates.TemplateResponse(
            "teacher_account.html", context, status_code=400
        )
    if new_password != confirm_password:
        context["error"] = "Xác nhận mật khẩu mới không khớp."
        return templates.TemplateResponse(
            "teacher_account.html", context, status_code=400
        )
    if pwd.verify(new_password, user.password_hash):
        context["error"] = "Mật khẩu mới phải khác mật khẩu hiện tại."
        return templates.TemplateResponse(
            "teacher_account.html", context, status_code=400
        )

    user.password_hash = pwd.hash(new_password)
    user.session_version += 1
    db.commit()
    context["user"] = user
    context["success"] = "Mật khẩu đã được thay đổi thành công."
    response = templates.TemplateResponse("teacher_account.html", context)
    set_session_cookie(response, user)
    return response

@router.post("/teacher/preferences")
def submit_teacher_preference(
    project_id: int = Form(...),
    preferred_slots: str = Form("[]"),
    unavailable_slots: str = Form("[]"),
    note: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if user.role != "teacher":
        raise HTTPException(403, "Chỉ tài khoản giáo viên được gửi nguyện vọng")
    project = teacher_view_project(user, db, project_id)
    if not project:
        raise HTTPException(404, "Không tìm thấy bộ thời khóa biểu")
    try:
        preferred_raw = json.loads(preferred_slots)
        unavailable_raw = json.loads(unavailable_slots)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(400, "Danh sách tiết nguyện vọng không hợp lệ") from exc
    preferred = valid_slots(project, preferred_raw, strict=True)
    unavailable = valid_slots(project, unavailable_raw, strict=True)
    overlap = sorted(set(preferred) & set(unavailable))
    if overlap:
        raise HTTPException(400, "Một tiết không thể vừa là mong muốn vừa là cần tránh")
    note = bounded_text(note, "Ghi chú", 2000, required=False)
    if not preferred and not unavailable and not note:
        raise HTTPException(
            400, "Hãy chọn ít nhất một tiết hoặc nhập ghi chú nguyện vọng"
        )
    # Mỗi lần gửi mới chỉ thay thế nguyện vọng đang chờ trước đó của chính tài
    # khoản này. Khóa row tài khoản để hai request đồng thời không thể cùng
    # nhìn thấy "không có pending" rồi tạo ra hai nguyện vọng đang chờ.
    # Không ghi sang Teacher.unavailable_json, không tạo constraint và không
    # gọi bất kỳ hàm xếp lịch nào.
    db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    pending_rows = db.scalars(
        select(TeacherPreference)
        .where(
            TeacherPreference.project_id == project.id,
            TeacherPreference.submitted_by_user_id == user.id,
            TeacherPreference.status == "pending",
        )
        .with_for_update()
    ).all()
    now_text = _utc_now_iso()
    for old in pending_rows:
        old.status = "superseded"
        old.reviewed_at = now_text
    db.add(
        TeacherPreference(
            project_id=project.id,
            teacher_id=None,
            submitted_by_user_id=user.id,
            submitted_name=user.name,
            submitted_email=user.email,
            preferred_json=json.dumps(preferred),
            unavailable_json=json.dumps(unavailable),
            note=note,
            status="pending",
        )
    )
    db.commit()
    return RedirectResponse(
        f"/teacher?project_id={project.id}&preference_saved=1#teacher-preferences", 303
    )

@router.get("/api/projects/{pid}/preferences")
def list_teacher_preferences(
    pid: int, user: User = Depends(current_user), db: Session = Depends(db_session)
):
    p = get_project(pid, user, db)
    return {"items": preference_payload(db, p)}

@router.delete("/api/projects/{pid}/preferences/{preference_id}")
def delete_teacher_preference(
    pid: int,
    preference_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    get_project_for_update(pid, user, db)
    preference = db.scalar(
        select(TeacherPreference)
        .where(
            TeacherPreference.id == preference_id,
            TeacherPreference.project_id == pid,
        )
        .with_for_update()
    )
    if not preference:
        raise HTTPException(404, "Không tìm thấy nguyện vọng")
    db.delete(preference)
    db.commit()
    return {"ok": True, "message": "Đã xóa nguyện vọng."}

@router.delete("/api/projects/{pid}/preferences")
def delete_all_teacher_preferences(
    pid: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    get_project_for_update(pid, user, db)
    rows = db.scalars(
        select(TeacherPreference)
        .where(TeacherPreference.project_id == pid)
        .with_for_update()
    ).all()
    deleted = len(rows)
    for preference in rows:
        db.delete(preference)
    db.commit()
    return {
        "ok": True,
        "deleted": deleted,
        "message": f"Đã xóa {deleted} nguyện vọng." if deleted else "Không có nguyện vọng để xóa.",
    }

@router.post("/api/projects/{pid}/preferences/{preference_id}/review")
def review_teacher_preference(
    pid: int,
    preference_id: int,
    payload: PreferenceReviewIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    get_project(pid, user, db)
    preference = db.scalar(
        select(TeacherPreference)
        .where(
            TeacherPreference.id == preference_id,
            TeacherPreference.project_id == pid,
        )
        .with_for_update()
    )
    if not preference:
        raise HTTPException(404, "Không tìm thấy nguyện vọng")
    if payload.action not in {"accept", "reject"}:
        raise HTTPException(400, "Thao tác không hợp lệ")
    if preference.status != "pending":
        raise HTTPException(409, "Nguyện vọng này đã được xử lý")

    # Nguyện vọng chỉ là dữ liệu tham khảo. Việc ghi nhận/từ chối không được
    # sửa lịch, không tạo constraint và không ảnh hưởng bất kỳ solver nào.
    preference.status = "accepted" if payload.action == "accept" else "rejected"
    preference.reviewed_at = _utc_now_iso()
    db.commit()
    return {
        "ok": True,
        "message": (
            "Đã ghi nhận nguyện vọng để tham khảo; thời khóa biểu không bị thay đổi."
            if payload.action == "accept"
            else "Đã từ chối nguyện vọng; thời khóa biểu không bị thay đổi."
        ),
    }

