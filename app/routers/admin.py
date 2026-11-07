from __future__ import annotations

from collections import defaultdict
from typing import Optional

from fastapi import (
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    ChatbotErrorLog,
    EmailChangeVerification,
    Project,
    School,
    TeacherPreference,
    User,
    UserSchool,
)
from app.services.authentication.credentials import pwd
from app.services.authentication.permissions import (
    admin_can_manage_account,
    is_admin,
    is_super_admin,
    user_greeting_name,
    user_school_ids,
)
from app.services.authentication.sessions import current_user, db_session, set_session_cookie
from app.services.avatars import prepare_avatar_change
from app.services.profiles import normalize_profile_url
from app.services.projects import chatbot_ui_context
from app.services.realtime.manager import realtime_manager
from app.services.web import bounded_text, redirect_with_notice, templates
from app.settings import MIN_PASSWORD_LENGTH

router = APIRouter()


@router.get("/admin/users", response_class=HTMLResponse)
def admin_users(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_admin(user):
        raise HTTPException(403, "Chỉ quản trị viên được quản lý tài khoản")
    projects_query = select(Project).where(Project.deleted_at.is_(None))
    if not is_super_admin(user):
        school_ids = user_school_ids(user, db)
        if school_ids:
            projects_query = projects_query.where(Project.school_id.in_(school_ids))
        else:
            projects_query = projects_query.where(Project.id == -1)
    projects = db.scalars(projects_query.order_by(Project.id.asc())).all()
    all_schools = db.scalars(select(School).order_by(School.name.asc())).all()
    assignable_school_ids = (
        {school.id for school in all_schools}
        if is_super_admin(user)
        else user_school_ids(user, db)
    )
    school_assignments = defaultdict(set)
    for link in db.scalars(select(UserSchool)).all():
        school_assignments[link.user_id].add(link.school_id)
    school_name_by_id = {school.id: school.name for school in all_schools}
    school_names_by_account = {
        account_id: [
            school_name_by_id[school_id]
            for school_id in sorted(school_ids)
            if school_id in school_name_by_id
        ]
        for account_id, school_ids in school_assignments.items()
    }
    all_users = db.scalars(select(User).order_by(User.id.asc())).all()
    users = [
        account for account in all_users if admin_can_manage_account(user, account, db)
    ]
    managed_account_ids = {
        account.id
        for account in users
        if account.role == "teacher" and admin_can_manage_account(user, account, db)
    }
    chatbot_error_logs = []
    chatbot_error_log_count = 0
    if is_super_admin(user):
        chatbot_error_log_count = db.scalar(select(func.count(ChatbotErrorLog.id))) or 0
        chatbot_error_logs = db.scalars(
            select(ChatbotErrorLog).order_by(ChatbotErrorLog.id.desc()).limit(100)
        ).all()
    return templates.TemplateResponse(
        "users.html",
        {
            "request": request,
            "user": user,
            "greeting_name": user_greeting_name(user),
            "users": users,
            "managed_account_ids": managed_account_ids,
            "schools": all_schools,
            "assignable_school_ids": assignable_school_ids,
            "school_assignments": school_assignments,
            "school_names_by_account": school_names_by_account,
            "chatbot_error_logs": chatbot_error_logs,
            "chatbot_error_log_count": chatbot_error_log_count,
            "online_user_ids": realtime_manager.online_user_ids_for(
                {account.id for account in users}
            ),
            **chatbot_ui_context(projects[-1] if projects else None),
        },
    )


@router.post("/admin/schools/create")
def create_school_from_account_management(
    name: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_super_admin(user):
        raise HTTPException(403, "Chỉ super admin được tạo trường")
    clean_name = bounded_text(name, "Tên trường", 200)
    existing = db.scalar(
        select(School).where(func.lower(School.name) == clean_name.lower())
    )
    if existing:
        return RedirectResponse("/admin/users", 303)
    db.add(School(name=clean_name))
    db.commit()
    return RedirectResponse("/admin/users", 303)


@router.post("/admin/schools/{school_id}/rename")
def rename_school_from_account_management(
    school_id: int,
    name: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_super_admin(user):
        raise HTTPException(403, "Chỉ super admin được sửa tên trường")

    school = db.get(School, school_id)
    if not school:
        raise HTTPException(404, "Không tìm thấy trường")

    try:
        clean_name = bounded_text(name, "Tên trường", 200)
    except HTTPException as exc:
        return redirect_with_notice("/admin/users", str(exc.detail))

    duplicate = db.scalar(
        select(School).where(
            School.id != school.id,
            func.lower(School.name) == clean_name.lower(),
        )
    )
    if duplicate:
        return redirect_with_notice("/admin/users", "Tên trường này đã tồn tại")

    if school.name != clean_name:
        school.name = clean_name
        # Project vẫn lưu school_name để hiển thị/xuất Excel, vì vậy cần đồng bộ
        # theo school_id mỗi khi đổi tên trường.
        projects = db.scalars(
            select(Project).where(Project.school_id == school.id)
        ).all()
        for project in projects:
            project.school_name = clean_name
        db.commit()
        return redirect_with_notice("/admin/users", "Đã đổi tên trường và cập nhật các bộ thời khóa biểu liên quan", kind="success")

    return redirect_with_notice("/admin/users", "Tên trường không thay đổi", kind="info")


@router.post("/admin/users/{account_id}/schools")
def update_account_schools(
    account_id: int,
    school_ids: list[int] = Form(default=[]),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_admin(user):
        raise HTTPException(403, "Chỉ quản trị viên được quản lý tài khoản")
    account = db.get(User, account_id)
    if not account:
        raise HTTPException(404, "Không tìm thấy tài khoản")

    if is_super_admin(user):
        if account.role not in {"admin", "teacher"}:
            raise HTTPException(
                403, "Super admin chỉ gán trường cho quản trị viên và giáo viên"
            )
        allowed_ids = set(db.scalars(select(School.id)).all())
    else:
        if account.role != "teacher":
            raise HTTPException(403, "Quản trị viên chỉ được gán trường cho giáo viên")
        if not admin_can_manage_account(user, account, db):
            raise HTTPException(403, "Giáo viên nằm ngoài phạm vi trường bạn quản lý")
        allowed_ids = user_school_ids(user, db)
        if not allowed_ids:
            raise HTTPException(403, "Tài khoản quản trị viên chưa được gán trường")

    requested_ids = {int(value) for value in school_ids}
    if not requested_ids.issubset(allowed_ids):
        raise HTTPException(403, "Có trường nằm ngoài phạm vi quản lý")

    existing = set(
        db.scalars(
            select(UserSchool.school_id).where(UserSchool.user_id == account.id)
        ).all()
    )
    if is_super_admin(user):
        desired = requested_ids
    else:
        # Admin thường chỉ thay đổi các trường thuộc phạm vi của mình, không được
        # vô tình xóa liên kết của giáo viên với trường do admin khác quản lý.
        desired = (existing - allowed_ids) | requested_ids

    to_remove = existing - desired
    if to_remove:
        db.execute(
            delete(UserSchool).where(
                UserSchool.user_id == account.id,
                UserSchool.school_id.in_(to_remove),
            )
        )
    for school_id in sorted(desired - existing):
        db.add(
            UserSchool(
                user_id=account.id,
                school_id=school_id,
                assigned_by_user_id=user.id,
            )
        )
    db.commit()
    return RedirectResponse("/admin/users", 303)


@router.post("/admin/chatbot-logs/clear")
def clear_chatbot_error_logs(
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_super_admin(user):
        raise HTTPException(403, "Chỉ super admin được xóa log chatbot")
    db.execute(delete(ChatbotErrorLog))
    db.commit()
    return RedirectResponse("/admin/users#chatbot-logs", 303)


@router.post("/admin/users/{account_id}/avatar")
def update_account_avatar(
    account_id: int,
    avatar_file: Optional[UploadFile] = File(None),
    remove_avatar: bool = Form(False),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_admin(user):
        raise HTTPException(403, "Chỉ quản trị viên được quản lý tài khoản")
    account = db.get(User, account_id)
    if not account or not admin_can_manage_account(user, account, db):
        raise HTTPException(404, "Không tìm thấy tài khoản trong phạm vi quản lý")
    try:
        avatar_change = prepare_avatar_change(avatar_file, remove_avatar, account.id)
    except (ValueError, HTTPException) as exc:
        msg = exc.detail if isinstance(exc, HTTPException) else str(exc)
        return redirect_with_notice("/admin/users", msg)
    if avatar_change is not None:
        account.avatar_url, account.avatar_image = avatar_change
        db.commit()
    return RedirectResponse("/admin/users", 303)


@router.post("/admin/users/{account_id}/update")
def update_account(
    account_id: int,
    name: str = Form(""),
    password: str = Form(""),
    profile_url: str = Form(""),
    avatar_file: Optional[UploadFile] = File(None),
    remove_avatar: bool = Form(False),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_admin(user):
        raise HTTPException(403, "Chỉ quản trị viên được quản lý tài khoản")
    account = db.get(User, account_id)
    if not account or not admin_can_manage_account(user, account, db):
        raise HTTPException(404, "Không tìm thấy tài khoản trong phạm vi quản lý")
    try:
        clean_name = bounded_text(name, "Họ tên", 120)
        clean_profile_url = normalize_profile_url(profile_url)
        avatar_change = prepare_avatar_change(avatar_file, remove_avatar, account.id)
    except ValueError as exc:
        return redirect_with_notice("/admin/users", str(exc))
    except HTTPException as exc:
        return redirect_with_notice("/admin/users", str(exc.detail))

    password_changed = bool(password.strip())
    clean_password = password.strip()
    if password_changed and len(clean_password) < MIN_PASSWORD_LENGTH:
        return redirect_with_notice(
            "/admin/users",
            f"Mật khẩu mới phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự",
        )

    account.name = clean_name
    account.profile_url = clean_profile_url
    if avatar_change is not None:
        account.avatar_url, account.avatar_image = avatar_change
    if password_changed:
        account.password_hash = pwd.hash(clean_password)
        account.session_version += 1
    db.commit()
    response = RedirectResponse("/admin/users", 303)
    if account.id == user.id and password_changed:
        set_session_cookie(response, account)
    return response


@router.post("/admin/users/{account_id}/delete")
def delete_account(
    account_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_admin(user):
        raise HTTPException(403, "Chỉ quản trị viên được quản lý tài khoản")
    account = db.get(User, account_id)
    if not account or not admin_can_manage_account(user, account, db):
        raise HTTPException(404, "Không tìm thấy tài khoản trong phạm vi quản lý")
    if account.id == user.id:
        raise HTTPException(400, "Không thể xóa chính tài khoản đang đăng nhập")
    if db.scalar(select(Project.id).where(Project.owner_id == account.id)) is not None:
        raise HTTPException(
            400, "Không thể xóa tài khoản đang sở hữu bộ thời khóa biểu"
        )
    db.execute(
        delete(EmailChangeVerification).where(
            (EmailChangeVerification.user_id == account.id)
            | (EmailChangeVerification.requested_by_user_id == account.id)
        )
    )
    # Giữ lịch sử nguyện vọng nhưng không để lại user_id mồ côi sau khi
    # tài khoản bị xóa. submitted_name/submitted_email vẫn là snapshot để
    # quản trị viên biết nguyện vọng trước đây do ai gửi.
    preferences = db.scalars(
        select(TeacherPreference).where(
            TeacherPreference.submitted_by_user_id == account.id
        )
    ).all()
    for preference in preferences:
        preference.submitted_by_user_id = None
    db.delete(account)
    db.commit()
    return RedirectResponse("/admin/users", 303)


@router.post("/admin/users/{account_id}/promote-admin")
def promote_teacher_to_admin(
    account_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if not is_super_admin(user):
        raise HTTPException(
            403, "Chỉ super admin được nâng giáo viên lên quản trị viên"
        )
    account = db.get(User, account_id)
    if not account:
        raise HTTPException(404, "Không tìm thấy tài khoản")
    if account.role != "teacher":
        raise HTTPException(
            400, "Chỉ có thể nâng tài khoản giáo viên lên quản trị viên"
        )
    account.role = "admin"
    # Thay đổi quyền phải vô hiệu toàn bộ cookie phiên cũ của tài khoản giáo viên.
    account.session_version += 1
    db.commit()
    return RedirectResponse("/admin/users", 303)
