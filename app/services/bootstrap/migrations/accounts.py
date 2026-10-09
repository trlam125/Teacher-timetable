from __future__ import annotations




def migrate_accounts(connection, inspector):
    columns = {column["name"] for column in inspector.get_columns("users")}
    role_was_added = "role" not in columns
    if role_was_added:
        connection.exec_driver_sql(
            "ALTER TABLE users "
            "ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'teacher'"
        )
    if "reset_token_hash" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE users ADD COLUMN reset_token_hash VARCHAR(64)"
        )
    if "reset_token_expires_at" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE users ADD COLUMN reset_token_expires_at VARCHAR(40)"
        )
    if "is_superadmin" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE users ADD COLUMN is_superadmin BOOLEAN NOT NULL DEFAULT FALSE"
        )
    if "session_version" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1"
        )
    if "last_seen" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE users ADD COLUMN last_seen VARCHAR(40)"
        )

    if "profile_url" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE users ADD COLUMN profile_url VARCHAR(2048) NOT NULL DEFAULT ''"
        )
    if "avatar_url" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE users ADD COLUMN avatar_url VARCHAR(2048) NOT NULL DEFAULT ''"
        )
        # The preceding release used profile_url for image links. Preserve
        # those images, but keep Facebook links in the actual profile field.
        connection.exec_driver_sql(
            "UPDATE users SET avatar_url = profile_url, profile_url = '' "
            "WHERE profile_url <> '' AND profile_url !~* %s",
            (r"^https?://([a-z0-9-]+\.)*(facebook\.com|fb\.com)([:/?#]|$)",),
        )
    if "avatar_image" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE users ADD COLUMN avatar_image BYTEA"
        )
