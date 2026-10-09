from __future__ import annotations

from datetime import datetime, timezone


def migrate_schools_and_chat(connection, inspector):
    if "projects" in inspector.get_table_names():
        project_columns = {
            column["name"] for column in inspector.get_columns("projects")
        }
        if "school_id" not in project_columns:
            connection.exec_driver_sql(
                "ALTER TABLE projects ADD COLUMN school_id INTEGER"
            )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_projects_school_id ON projects (school_id)"
        )
        # Chuẩn hóa các tên trường đã có thành bảng schools. Việc gán trường
        # cho tài khoản vẫn để quản trị viên thực hiện thủ công ở Quản lý tài khoản.
        connection.exec_driver_sql(
            "INSERT INTO schools (name, created_at) "
            "SELECT DISTINCT TRIM(school_name), %s FROM projects "
            "WHERE school_name IS NOT NULL AND TRIM(school_name)<>'' "
            "ON CONFLICT (name) DO NOTHING",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"),),
        )
        connection.exec_driver_sql(
            "UPDATE projects p SET school_id=s.id FROM schools s "
            "WHERE p.school_id IS NULL AND TRIM(p.school_name)=s.name"
        )

    if "chat_messages" in inspector.get_table_names():
        chat_columns = {
            column["name"] for column in inspector.get_columns("chat_messages")
        }
        if "school_id" not in chat_columns:
            connection.exec_driver_sql(
                "ALTER TABLE chat_messages ADD COLUMN school_id INTEGER"
            )
        if "reply_to_id" not in chat_columns:
            connection.exec_driver_sql(
                "ALTER TABLE chat_messages ADD COLUMN reply_to_id INTEGER"
            )
        if "edited_at" not in chat_columns:
            connection.exec_driver_sql(
                "ALTER TABLE chat_messages ADD COLUMN edited_at VARCHAR(40)"
            )
        if "deleted_at" not in chat_columns:
            connection.exec_driver_sql(
                "ALTER TABLE chat_messages ADD COLUMN deleted_at VARCHAR(40)"
            )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_chat_messages_reply_to_id "
            "ON chat_messages (reply_to_id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_chat_messages_school_id "
            "ON chat_messages (school_id)"
        )
