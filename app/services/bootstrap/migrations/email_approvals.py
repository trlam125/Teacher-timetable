def migrate_email_approvals(connection, inspector):
    columns = {column["name"] for column in inspector.get_columns("email_change_verifications")}
    additions = {
        "verification_email": "VARCHAR(255) NOT NULL DEFAULT ''",
        "actor_session_version": "INTEGER NOT NULL DEFAULT 0",
        "target_session_version": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, definition in additions.items():
        if name not in columns:
            connection.exec_driver_sql(f"ALTER TABLE email_change_verifications ADD COLUMN {name} {definition}")
