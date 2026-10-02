from __future__ import annotations

from app.services.foundation import *
from app.services.auth import *
from app.services.projects import *


def seed_project(db: Session, p: Project):
    d1 = Department(project_id=p.id, name="Tổ Toán - Tin")
    d2 = Department(project_id=p.id, name="Tổ Ngữ văn")
    db.add_all([d1, d2])
    db.flush()
    s1 = Subject(project_id=p.id, name="Toán", short_name="TOÁN", max_consecutive=2)
    s2 = Subject(project_id=p.id, name="Ngữ văn", short_name="VĂN", max_consecutive=2)
    s3 = Subject(project_id=p.id, name="Tin học", short_name="TIN", max_consecutive=1)
    db.add_all([s1, s2, s3])
    db.flush()
    t1 = Teacher(
        project_id=p.id,
        department_id=d1.id,
        name="Nguyễn Văn An",
        short_name="An",
        max_periods_day=4,
    )
    t2 = Teacher(
        project_id=p.id,
        department_id=d2.id,
        name="Trần Thị Bình",
        short_name="Bình",
        max_periods_day=4,
    )
    t3 = Teacher(
        project_id=p.id,
        department_id=d1.id,
        name="Lê Minh Châu",
        short_name="Châu",
        max_periods_day=4,
    )
    db.add_all([t1, t2, t3])
    db.flush()
    db.add_all(
        [
            TeacherSubject(project_id=p.id, teacher_id=t1.id, subject_id=s1.id),
            TeacherSubject(project_id=p.id, teacher_id=t2.id, subject_id=s2.id),
            TeacherSubject(project_id=p.id, teacher_id=t3.id, subject_id=s3.id),
        ]
    )
    g = Grade(project_id=p.id, name="Khối 10")
    db.add(g)
    db.flush()
    c1 = SchoolClass(project_id=p.id, grade_id=g.id, name="10A1")
    c2 = SchoolClass(project_id=p.id, grade_id=g.id, name="10A2")
    db.add_all([c1, c2])
    db.flush()
    for c in [c1, c2]:
        db.add_all(
            [
                Assignment(
                    project_id=p.id,
                    class_id=c.id,
                    subject_id=s1.id,
                    teacher_id=t1.id,
                    periods_per_week=4,
                ),
                Assignment(
                    project_id=p.id,
                    class_id=c.id,
                    subject_id=s2.id,
                    teacher_id=t2.id,
                    periods_per_week=3,
                ),
                Assignment(
                    project_id=p.id,
                    class_id=c.id,
                    subject_id=s3.id,
                    teacher_id=t3.id,
                    periods_per_week=2,
                ),
            ]
        )
    db.commit()


def ensure_demo():
    db = SessionLocal()
    try:
        existing_super_admin = db.scalar(
            select(User)
            .where(User.role == "super_admin")
            .order_by(User.id.asc())
            .limit(1)
        )
        configured_target = (
            db.get(User, SUPER_ADMIN_USER_ID) if SUPER_ADMIN_USER_ID > 0 else None
        )
        if SUPER_ADMIN_USER_ID > 0 and configured_target is None:
            logger.error(
                "SUPER_ADMIN_USER_ID=%s không tồn tại; không hạ quyền super_admin hiện tại.",
                SUPER_ADMIN_USER_ID,
            )
            if existing_super_admin is not None:
                return

        email_target = (
            db.scalar(
                select(User)
                .where(func.lower(User.email) == BOOTSTRAP_ADMIN_EMAIL)
                .limit(1)
            )
            if BOOTSTRAP_ADMIN_EMAIL
            else None
        )
        target = (
            configured_target
            if configured_target is not None
            else (existing_super_admin or email_target)
        )

        if target is not None and target.role == "super_admin":
            changed = not bool(target.is_superadmin)
            target.is_superadmin = True
            for other in db.scalars(
                select(User).where(User.role == "super_admin", User.id != target.id)
            ).all():
                other.role = "admin"
                other.is_superadmin = False
                changed = True
            if changed:
                db.commit()
            return

        if target is None and (
            not BOOTSTRAP_ADMIN_EMAIL or len(BOOTSTRAP_ADMIN_PASSWORD) < 8
        ):
            if existing_super_admin is not None:
                return
            raise RuntimeError(
                "Database chưa có super admin. Hãy cấu hình SUPER_ADMIN_USER_ID trỏ tới "
                "một tài khoản tồn tại hoặc cấu hình BOOTSTRAP_ADMIN_EMAIL và "
                "BOOTSTRAP_ADMIN_PASSWORD (ít nhất 8 ký tự) để khôi phục quyền quản trị."
            )

        user = target
        if user is None:
            user = User(
                email=BOOTSTRAP_ADMIN_EMAIL,
                name="Quản trị viên",
                password_hash=pwd.hash(BOOTSTRAP_ADMIN_PASSWORD),
                role="super_admin",
                is_superadmin=True,
            )
            db.add(user)
            db.flush()
        else:
            user.role = "super_admin"
            user.is_superadmin = True
            if BOOTSTRAP_ADMIN_EMAIL and len(BOOTSTRAP_ADMIN_PASSWORD) >= 8:
                user.password_hash = pwd.hash(BOOTSTRAP_ADMIN_PASSWORD)
                user.session_version = max(1, user.session_version or 1) + 1
            if not (user.name or "").strip():
                user.name = "Quản trị viên"

        # Chỉ hạ các super_admin khác sau khi tài khoản đích đã tồn tại trong
        # transaction hiện tại. Nhờ vậy cấu hình sai không thể làm mất quyền.
        for other in db.scalars(
            select(User).where(User.role == "super_admin", User.id != user.id)
        ).all():
            other.role = "admin"
            other.is_superadmin = False

        db.commit()
        if SEED_DEMO_DATA and db.scalar(select(Project.id).limit(1)) is None:
            school = ensure_school_for_name(db, "THPT Demo")
            p = Project(
                owner_id=user.id,
                school_id=school.id,
                name="TKB học kỳ I",
                school_name=school.name,
                days=6,
                sessions=2,
                periods_per_session=5,
            )
            db.add(p)
            db.commit()
            seed_project(db, p)
    finally:
        db.close()


__all__ = [name for name in globals() if not name.startswith("__")]
