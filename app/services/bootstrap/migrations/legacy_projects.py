from __future__ import annotations

import json
import os
from app.logic import (
    parse_integer_set,
    remap_slot_for_session_expansion,
    remap_slots_for_session_expansion,
)
from app.services.foundation import logger
from datetime import datetime, timezone


def migrate_legacy_projects(connection, inspector):
    if "projects" in inspector.get_table_names():
        project_columns = {
            column["name"] for column in inspector.get_columns("projects")
        }
        if "blocked_slots_json" not in project_columns:
            connection.exec_driver_sql(
                "ALTER TABLE projects ADD COLUMN blocked_slots_json TEXT NOT NULL DEFAULT '[]'"
            )

        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS app_data_migrations ("
            "migration_key VARCHAR(200) PRIMARY KEY, "
            "applied_at VARCHAR(40) NOT NULL"
            ")"
        )

        configured_ids = os.getenv("LEGACY_DEMO_SESSION_EXPANSION_PROJECT_IDS", "")
        legacy_demo_project_ids = set()
        for raw_id in configured_ids.split(","):
            raw_id = raw_id.strip()
            if not raw_id:
                continue
            try:
                project_id = int(raw_id)
            except ValueError:
                logger.warning(
                    "Bỏ qua project_id migration demo không hợp lệ: %r", raw_id
                )
                continue
            if project_id > 0:
                legacy_demo_project_ids.add(project_id)

        for project_id in sorted(legacy_demo_project_ids):
            migration_key = f"legacy_demo_session_expansion_v1:{project_id}"
            already_applied = connection.exec_driver_sql(
                "SELECT 1 FROM app_data_migrations WHERE migration_key=%s",
                (migration_key,),
            ).scalar()
            if already_applied:
                continue

            legacy_project = (
                connection.exec_driver_sql(
                    "SELECT id, periods_per_session, blocked_slots_json FROM projects "
                    "WHERE id=%s AND sessions=1",
                    (project_id,),
                )
                .mappings()
                .first()
            )
            if legacy_project is None:
                logger.warning(
                    "Không migrate project %s: không tồn tại hoặc sessions không còn là 1.",
                    project_id,
                )
                continue

            periods_per_session = int(legacy_project["periods_per_session"])

            def remap_json_slots(raw_value):
                return json.dumps(
                    remap_slots_for_session_expansion(
                        parse_integer_set(raw_value),
                        old_sessions=1,
                        new_sessions=2,
                        periods_per_session=periods_per_session,
                    )
                )

            connection.exec_driver_sql(
                "UPDATE projects SET blocked_slots_json=%s WHERE id=%s",
                (
                    remap_json_slots(legacy_project["blocked_slots_json"]),
                    project_id,
                ),
            )

            for table_name in ("lessons", "fixed_lessons"):
                if table_name not in inspector.get_table_names():
                    continue
                rows = (
                    connection.exec_driver_sql(
                        f"SELECT id, slot FROM {table_name} WHERE project_id=%s",
                        (project_id,),
                    )
                    .mappings()
                    .all()
                )
                for row in rows:
                    mapped_slot = remap_slot_for_session_expansion(
                        row["slot"],
                        old_sessions=1,
                        new_sessions=2,
                        periods_per_session=periods_per_session,
                    )
                    connection.exec_driver_sql(
                        f"UPDATE {table_name} SET slot=%s WHERE id=%s",
                        (mapped_slot, row["id"]),
                    )

            json_slot_columns = {
                "teachers": ("unavailable_json",),
                "classes": ("unavailable_json",),
                "teacher_preferences": ("preferred_json", "unavailable_json"),
            }
            for table_name, column_names in json_slot_columns.items():
                if table_name not in inspector.get_table_names():
                    continue
                selected_columns = ", ".join(("id", *column_names))
                rows = (
                    connection.exec_driver_sql(
                        f"SELECT {selected_columns} FROM {table_name} WHERE project_id=%s",
                        (project_id,),
                    )
                    .mappings()
                    .all()
                )
                for row in rows:
                    assignments_sql = ", ".join(
                        f"{column}=%s" for column in column_names
                    )
                    values = tuple(
                        remap_json_slots(row[column]) for column in column_names
                    )
                    connection.exec_driver_sql(
                        f"UPDATE {table_name} SET {assignments_sql} WHERE id=%s",
                        (*values, row["id"]),
                    )

            connection.exec_driver_sql(
                "UPDATE projects SET sessions=2 WHERE id=%s",
                (project_id,),
            )
            connection.exec_driver_sql(
                "INSERT INTO app_data_migrations (migration_key, applied_at) "
                "VALUES (%s, %s)",
                (migration_key, datetime.now(timezone.utc).isoformat()),
            )
