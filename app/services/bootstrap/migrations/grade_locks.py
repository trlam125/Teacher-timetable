from __future__ import annotations


def migrate_grade_locks(connection, inspector):
    if "grades" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("grades")}
    if "blocked_slots_json" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE grades ADD COLUMN blocked_slots_json TEXT NOT NULL DEFAULT '[]'"
        )
