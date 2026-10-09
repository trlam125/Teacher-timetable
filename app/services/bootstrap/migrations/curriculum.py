from __future__ import annotations




def migrate_curriculum(connection, inspector):
    if (
        "teacher_subjects" in inspector.get_table_names()
        and "assignments" in inspector.get_table_names()
    ):
        connection.exec_driver_sql(
            "INSERT INTO teacher_subjects (project_id, teacher_id, subject_id) "
            "SELECT DISTINCT project_id, teacher_id, subject_id FROM assignments "
            "ON CONFLICT (project_id, teacher_id, subject_id) DO NOTHING"
        )

    if "assignments" in inspector.get_table_names():
        duplicate_assignment_pairs = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM ("
            "SELECT project_id, class_id, subject_id FROM assignments "
            "GROUP BY project_id, class_id, subject_id HAVING COUNT(*) > 1"
            ") duplicate_pairs"
        ).scalar()
        if not duplicate_assignment_pairs:
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_assignment_class_subject "
                "ON assignments (project_id, class_id, subject_id)"
            )

    assignment_columns = (
        {column["name"] for column in inspector.get_columns("assignments")}
        if "assignments" in inspector.get_table_names()
        else set()
    )
    if assignment_columns and "block_mode" not in assignment_columns:
        connection.exec_driver_sql(
            "ALTER TABLE assignments ADD COLUMN block_mode VARCHAR(24) NOT NULL DEFAULT 'free'"
        )
        # Mẫu cũ chỉ gồm 1 và 2, đồng thời có ít nhất một số 2, được
        # chuyển sang bắt buộc tiết đôi. Mẫu có cụm 3+ chuyển thành tự do
        # vì chế độ mới không còn hỗ trợ cụm tùy ý.
        connection.exec_driver_sql(
            "UPDATE assignments SET block_mode='required_double' "
            "WHERE consecutive_pattern ~ '(^|,)[[:space:]]*2[[:space:]]*(,|$)' "
            "AND COALESCE(regexp_replace(consecutive_pattern, '[[:space:]12,]', '', 'g'), '') = ''"
        )
        connection.exec_driver_sql("UPDATE assignments SET consecutive_pattern=''")

    fixed_columns = (
        {column["name"] for column in inspector.get_columns("fixed_lessons")}
        if "fixed_lessons" in inspector.get_table_names()
        else set()
    )
    if fixed_columns and "group_size" not in fixed_columns:
        connection.exec_driver_sql(
            "ALTER TABLE fixed_lessons ADD COLUMN group_size INTEGER NOT NULL DEFAULT 1"
        )
    if fixed_columns:
        # Xóa bản ghi trùng do dữ liệu cũ/import thủ công rồi khóa bất biến
        # mỗi assignment chỉ có một FixedLesson tại cùng một slot.
        connection.exec_driver_sql(
            "DELETE FROM fixed_lessons newer USING fixed_lessons older "
            "WHERE newer.id>older.id "
            "AND newer.project_id=older.project_id "
            "AND newer.assignment_id=older.assignment_id "
            "AND newer.slot=older.slot"
        )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_fixed_lesson "
            "ON fixed_lessons (project_id, assignment_id, slot)"
        )
    if fixed_columns and "assignments" in inspector.get_table_names():
        # Ở chế độ tự do/ưu tiên, mỗi ghim là một tiết độc lập. Chuyển các
        # ghim cụm cũ thành từng ghim đơn để không tạo tiết khóa mồ côi.
        connection.exec_driver_sql(
            "UPDATE fixed_lessons SET group_size=1 FROM assignments "
            "WHERE fixed_lessons.assignment_id=assignments.id "
            "AND assignments.block_mode<>'required_double'"
        )
        if "lessons" in inspector.get_table_names():
            connection.exec_driver_sql(
                "INSERT INTO fixed_lessons (project_id, assignment_id, slot, group_size) "
                "SELECT lessons.project_id, lessons.assignment_id, lessons.slot, 1 "
                "FROM lessons JOIN assignments ON assignments.id=lessons.assignment_id "
                "WHERE lessons.locked=TRUE AND assignments.block_mode<>'required_double' "
                "AND NOT EXISTS (SELECT 1 FROM fixed_lessons "
                "WHERE fixed_lessons.assignment_id=lessons.assignment_id "
                "AND fixed_lessons.slot=lessons.slot)"
            )
