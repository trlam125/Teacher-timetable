from __future__ import annotations

import os
from app.services.foundation import logger


def migrate_account_roles(connection, inspector):
    connection.exec_driver_sql(
        "UPDATE users SET role='teacher' WHERE role IS NULL OR role='' OR role IN ('user', 'pending')"
    )
    bootstrap_email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    try:
        configured_super_admin_id = int(os.getenv("SUPER_ADMIN_USER_ID", "0") or 0)
    except ValueError:
        configured_super_admin_id = 0

    configured_super_admin_exists = False
    if configured_super_admin_id > 0:
        configured_super_admin_exists = (
            connection.exec_driver_sql(
                "SELECT 1 FROM users WHERE id=%s",
                (configured_super_admin_id,),
            ).first()
            is not None
        )
        if not configured_super_admin_exists:
            logger.error(
                "SUPER_ADMIN_USER_ID=%s không tồn tại; giữ nguyên super_admin hiện tại.",
                configured_super_admin_id,
            )

    existing_super_admin_id = connection.exec_driver_sql(
        "SELECT id FROM users WHERE role='super_admin' ORDER BY id ASC LIMIT 1"
    ).scalar()
    bootstrap_super_admin_exists = False
    # BOOTSTRAP_ADMIN_EMAIL chỉ dùng để khởi tạo/khôi phục khi database chưa
    # có super_admin. Sau khi super admin đổi email, không được tạo lại tài
    # khoản email bootstrap cũ rồi hạ quyền tài khoản hiện tại.
    if (
        configured_super_admin_id <= 0
        and existing_super_admin_id is None
        and bootstrap_email
    ):
        bootstrap_super_admin_exists = (
            connection.exec_driver_sql(
                "SELECT 1 FROM users WHERE lower(email)=lower(%s)",
                (bootstrap_email,),
            ).first()
            is not None
        )

    if "projects" in inspector.get_table_names():
        # Keep valid 5-7 day schedules intact. Only repair missing or
        # out-of-range legacy values so a 5-day project survives restarts.
        connection.exec_driver_sql(
            "UPDATE projects SET days=6 WHERE days IS NULL OR days<5 OR days>7"
        )

        connection.exec_driver_sql(
            "ALTER TABLE projects DROP COLUMN IF EXISTS teacher_invite_token"
        )

        # Chủ project thường giữ role admin. Chỉ hạ quyền super_admin khi
        # đã xác nhận chắc chắn tài khoản đích tồn tại; cấu hình sai không
        # được phép làm hệ thống mất toàn bộ super_admin.
        if configured_super_admin_exists:
            connection.exec_driver_sql(
                "UPDATE users SET role='admin', is_superadmin=FALSE "
                "WHERE id IN (SELECT DISTINCT owner_id FROM projects) AND id<>%s",
                (configured_super_admin_id,),
            )
        elif configured_super_admin_id <= 0 and bootstrap_super_admin_exists:
            connection.exec_driver_sql(
                "UPDATE users SET role='admin', is_superadmin=FALSE "
                "WHERE id IN (SELECT DISTINCT owner_id FROM projects) "
                "AND lower(email)<>lower(%s)",
                (bootstrap_email,),
            )
        else:
            connection.exec_driver_sql(
                "UPDATE users SET role='admin', is_superadmin=FALSE "
                "WHERE id IN (SELECT DISTINCT owner_id FROM projects) "
                "AND role<>'super_admin'"
            )
    if "registration_verifications" in inspector.get_table_names():
        connection.exec_driver_sql(
            "ALTER TABLE registration_verifications "
            "DROP COLUMN IF EXISTS project_id, "
            "DROP COLUMN IF EXISTS teacher_id, "
            "DROP COLUMN IF EXISTS requested_teacher_name"
        )
    if "teacher_account_links" in inspector.get_table_names():
        connection.exec_driver_sql("DROP TABLE teacher_account_links")
    # teacher_preferences được giữ lại có chủ đích như dữ liệu tham khảo.
    # Từ phiên bản này, nguyện vọng mới gắn với tài khoản đã xác minh email
    # thay vì hồ sơ Teacher, để không khôi phục cơ chế gán account -> Teacher.
    if "teacher_preferences" in inspector.get_table_names():
        preference_columns = {
            column["name"]
            for column in inspector.get_columns("teacher_preferences")
        }
        if "submitted_by_user_id" not in preference_columns:
            connection.exec_driver_sql(
                "ALTER TABLE teacher_preferences ADD COLUMN submitted_by_user_id INTEGER"
            )
        if "submitted_name" not in preference_columns:
            connection.exec_driver_sql(
                "ALTER TABLE teacher_preferences ADD COLUMN submitted_name VARCHAR(120) NOT NULL DEFAULT ''"
            )
        if "submitted_email" not in preference_columns:
            connection.exec_driver_sql(
                "ALTER TABLE teacher_preferences ADD COLUMN submitted_email VARCHAR(255) NOT NULL DEFAULT ''"
            )
        connection.exec_driver_sql(
            "ALTER TABLE teacher_preferences ALTER COLUMN teacher_id DROP NOT NULL"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_teacher_preferences_submitted_by_user_id "
            "ON teacher_preferences (submitted_by_user_id)"
        )
        # Dữ liệu cũ có thể còn user_id trỏ tới tài khoản đã bị xóa.
        # Dọn các giá trị mồ côi trước khi bổ sung khóa ngoại để migration
        # chạy được trên database đang sử dụng.
        connection.exec_driver_sql(
            "UPDATE teacher_preferences preference "
            "SET submitted_by_user_id=NULL "
            "WHERE submitted_by_user_id IS NOT NULL "
            "AND NOT EXISTS ("
            "SELECT 1 FROM users WHERE users.id=preference.submitted_by_user_id"
            ")"
        )
        connection.exec_driver_sql(
            "DO $$ "
            "BEGIN "
            "IF NOT EXISTS ("
            "SELECT 1 FROM pg_constraint "
            "WHERE conname='fk_teacher_preferences_submitted_by_user_id'"
            ") THEN "
            "ALTER TABLE teacher_preferences "
            "ADD CONSTRAINT fk_teacher_preferences_submitted_by_user_id "
            "FOREIGN KEY (submitted_by_user_id) REFERENCES users(id) "
            "ON DELETE SET NULL; "
            "END IF; "
            "END $$"
        )
    # Không migrate nguyện vọng thành teacher.unavailable_json và không dùng
    # chúng làm ràng buộc xếp lịch.
    connection.exec_driver_sql(
        "ALTER TABLE users ALTER COLUMN role SET DEFAULT 'teacher'"
    )
    if configured_super_admin_exists:
        connection.exec_driver_sql(
            "UPDATE users SET role=CASE WHEN role='super_admin' THEN 'admin' ELSE role END, "
            "is_superadmin=FALSE WHERE id<>%s",
            (configured_super_admin_id,),
        )
        connection.exec_driver_sql(
            "UPDATE users SET role='super_admin', is_superadmin=TRUE WHERE id=%s",
            (configured_super_admin_id,),
        )
    elif configured_super_admin_id <= 0 and bootstrap_super_admin_exists:
        connection.exec_driver_sql(
            "UPDATE users SET role=CASE WHEN role='super_admin' THEN 'admin' ELSE role END, "
            "is_superadmin=FALSE WHERE lower(email)<>lower(%s)",
            (bootstrap_email,),
        )
        connection.exec_driver_sql(
            "UPDATE users SET role='super_admin', is_superadmin=TRUE "
            "WHERE lower(email)=lower(%s)",
            (bootstrap_email,),
        )

    connection.exec_driver_sql(
        "ALTER TABLE users "
        "DROP COLUMN IF EXISTS teacher_id, "
        "DROP COLUMN IF EXISTS requested_teacher_name, "
        "DROP COLUMN IF EXISTS requested_project_id"
    )
