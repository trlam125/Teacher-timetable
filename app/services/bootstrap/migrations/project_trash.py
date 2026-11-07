from __future__ import annotations


def migrate_project_trash(connection, inspector):
    if "projects" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("projects")}
    if "deleted_at" not in columns:
        connection.exec_driver_sql("ALTER TABLE projects ADD COLUMN deleted_at VARCHAR(40)")
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_projects_deleted_at ON projects (deleted_at)"
    )
