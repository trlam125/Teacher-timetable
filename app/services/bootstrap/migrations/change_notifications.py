def migrate_change_notifications(connection, inspector):
    if "project_changes" in inspector.get_table_names():
        change_columns = {column["name"] for column in inspector.get_columns("project_changes")}
        if "audit_json" not in change_columns:
            connection.exec_driver_sql("ALTER TABLE project_changes ADD COLUMN audit_json TEXT NOT NULL DEFAULT '{}'")
    if "schedule_notifications" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("schedule_notifications")}
    if "summary_text" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE schedule_notifications ADD COLUMN summary_text TEXT NOT NULL DEFAULT ''"
        )
