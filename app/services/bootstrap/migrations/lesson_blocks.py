from __future__ import annotations




def migrate_lesson_blocks(connection, inspector):
    if "lessons" in inspector.get_table_names():
        lesson_columns = {
            column["name"] for column in inspector.get_columns("lessons")
        }
        block_id_added = "block_id" not in lesson_columns
        block_size_added = "block_size" not in lesson_columns
        if block_id_added:
            connection.exec_driver_sql(
                "ALTER TABLE lessons ADD COLUMN block_id VARCHAR(64)"
            )
        if block_size_added:
            connection.exec_driver_sql(
                "ALTER TABLE lessons ADD COLUMN block_size INTEGER NOT NULL DEFAULT 1"
            )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_lessons_block_id ON lessons (block_id)"
        )
        if "assignments" in inspector.get_table_names():
            connection.exec_driver_sql(
                "UPDATE lessons l SET block_id='single-' || l.id::text "
                "FROM assignments a WHERE a.id=l.assignment_id "
                "AND a.block_mode<>'required_double' AND l.block_id IS NULL"
            )
            connection.exec_driver_sql(
                "UPDATE lessons l SET block_size=1 FROM assignments a "
                "WHERE a.id=l.assignment_id AND a.block_mode<>'required_double'"
            )

            legacy_rows = (
                connection.exec_driver_sql(
                    "SELECT a.id AS assignment_id, p.sessions, p.periods_per_session, "
                    "l.id AS lesson_id, l.slot "
                    "FROM assignments a "
                    "JOIN projects p ON p.id=a.project_id "
                    "JOIN lessons l ON l.assignment_id=a.id "
                    "WHERE a.block_mode='required_double' AND l.block_id IS NULL "
                    "ORDER BY a.id, l.slot, l.id"
                )
                .mappings()
                .all()
            )
            grouped = {}
            for row in legacy_rows:
                grouped.setdefault(int(row["assignment_id"]), []).append(row)
            for assignment_id, rows in grouped.items():
                sessions = int(rows[0]["sessions"])
                pps = int(rows[0]["periods_per_session"])
                ppd = sessions * pps
                runs = []
                current = []
                previous_slot = None
                previous_key = None
                for row in rows:
                    slot = int(row["slot"])
                    key = (slot // ppd, (slot % ppd) // pps)
                    if current and (
                        key != previous_key or slot != previous_slot + 1
                    ):
                        runs.append(current)
                        current = []
                    current.append(row)
                    previous_slot = slot
                    previous_key = key
                if current:
                    runs.append(current)

                ordinal = 0
                for run in runs:
                    index = 0
                    while index < len(run):
                        size = 2 if index + 1 < len(run) else 1
                        block_id = f"migrated-rd-{assignment_id}-{ordinal}"
                        ordinal += 1
                        for row in run[index : index + size]:
                            connection.exec_driver_sql(
                                "UPDATE lessons SET block_id=%s, block_size=%s WHERE id=%s AND block_id IS NULL",
                                (block_id, size, int(row["lesson_id"])),
                            )
                        index += size

            # Only infer size for installations upgrading from a schema that
            # already had block_id but not block_size. On subsequent starts,
            # block_size is immutable metadata: a lost member of a size-2 block
            # must remain detectable instead of being silently retyped as size 1.
            if block_size_added:
                connection.exec_driver_sql(
                    "UPDATE lessons l SET block_size=g.cnt FROM ("
                    "SELECT l2.assignment_id, l2.block_id, COUNT(*)::int AS cnt "
                    "FROM lessons l2 JOIN assignments a2 ON a2.id=l2.assignment_id "
                    "WHERE a2.block_mode='required_double' AND l2.block_id IS NOT NULL "
                    "GROUP BY l2.assignment_id, l2.block_id"
                    ") g WHERE l.assignment_id=g.assignment_id AND l.block_id=g.block_id"
                )
