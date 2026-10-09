from __future__ import annotations

from app.models import School, User, UserSchool
from app.services.foundation import ADMIN_ROLES
from sqlalchemy import select
from sqlalchemy.orm import Session


def is_admin(user: User) -> bool:
    return user.role in ADMIN_ROLES


def is_super_admin(user: User) -> bool:
    return user.role == "super_admin"


def user_greeting_name(user: User) -> str:
    # Lời chào dùng đúng họ tên/tên hiển thị lưu trong hồ sơ người dùng.
    # Không suy ra tên từ phần trước dấu @ của email vì đó chỉ là tên tài khoản.
    return (user.name or "").strip() or "Người dùng"


def user_school_ids(user: User, db: Session) -> set[int]:
    if is_super_admin(user):
        return set(db.scalars(select(School.id)).all())
    return set(
        db.scalars(
            select(UserSchool.school_id).where(UserSchool.user_id == user.id)
        ).all()
    )


def user_schools(user: User, db: Session) -> list[School]:
    if is_super_admin(user):
        return db.scalars(select(School).order_by(School.name.asc())).all()
    ids = user_school_ids(user, db)
    if not ids:
        return []
    return db.scalars(
        select(School).where(School.id.in_(ids)).order_by(School.name.asc())
    ).all()


def user_can_access_school(user: User, school_id: int | None, db: Session) -> bool:
    if is_super_admin(user):
        return True
    if school_id is None:
        return False
    return school_id in user_school_ids(user, db)


def admin_can_manage_account(
    admin: User, account: User, db: Session | None = None
) -> bool:
    if not is_admin(admin):
        return False
    if account.id == admin.id:
        return True
    if is_super_admin(admin):
        return account.role != "super_admin"
    if account.role != "teacher" or db is None:
        return False

    admin_school_ids = user_school_ids(admin, db)
    if not admin_school_ids:
        return False
    account_school_ids = set(
        db.scalars(
            select(UserSchool.school_id).where(UserSchool.user_id == account.id)
        ).all()
    )
    # Giáo viên chưa có trường có thể được một admin có trường nhận vào phạm vi
    # quản lý; giáo viên đã có trường chỉ hiện cho admin có ít nhất một trường chung.
    return not account_school_ids or bool(admin_school_ids & account_school_ids)
