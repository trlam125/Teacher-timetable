def migrate_login_alert_limits(connection, inspector):
    columns = {column["name"] for column in inspector.get_columns("email_delivery_jobs")}
    if "quota_day" not in columns:
        connection.exec_driver_sql("ALTER TABLE email_delivery_jobs ADD COLUMN quota_day INTEGER NOT NULL DEFAULT 0")
