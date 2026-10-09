from __future__ import annotations




def migrate_entity_integrity(connection, inspector):
    if "assignments" in inspector.get_table_names():
        connection.exec_driver_sql(
            """
                CREATE OR REPLACE FUNCTION enforce_assignment_project_integrity()
                RETURNS trigger AS $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM classes WHERE id=NEW.class_id AND project_id=NEW.project_id) THEN
                        RAISE EXCEPTION 'Lớp không thuộc cùng project với phân công.' USING ERRCODE='23514';
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM subjects WHERE id=NEW.subject_id AND project_id=NEW.project_id) THEN
                        RAISE EXCEPTION 'Môn học không thuộc cùng project với phân công.' USING ERRCODE='23514';
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM teachers WHERE id=NEW.teacher_id AND project_id=NEW.project_id) THEN
                        RAISE EXCEPTION 'Giáo viên không thuộc cùng project với phân công.' USING ERRCODE='23514';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
        )
        connection.exec_driver_sql(
            "DROP TRIGGER IF EXISTS trg_assignment_project_integrity ON assignments"
        )
        connection.exec_driver_sql(
            """
                CREATE TRIGGER trg_assignment_project_integrity
                BEFORE INSERT OR UPDATE OF project_id, class_id, subject_id, teacher_id
                ON assignments FOR EACH ROW
                EXECUTE FUNCTION enforce_assignment_project_integrity()
                """
        )
        invalid_assignments = connection.exec_driver_sql(
            """
                SELECT COUNT(*) FROM assignments a
                LEFT JOIN classes c ON c.id=a.class_id
                LEFT JOIN subjects s ON s.id=a.subject_id
                LEFT JOIN teachers t ON t.id=a.teacher_id
                WHERE c.id IS NULL OR s.id IS NULL OR t.id IS NULL
                   OR c.project_id<>a.project_id
                   OR s.project_id<>a.project_id
                   OR t.project_id<>a.project_id
                """
        ).scalar()
        if invalid_assignments:
            raise RuntimeError(
                f"Phát hiện {invalid_assignments} phân công có tham chiếu chéo project. "
                "Hãy sửa dữ liệu trước khi khởi động ứng dụng."
            )

    if (
        "fixed_lessons" in inspector.get_table_names()
        and "assignments" in inspector.get_table_names()
    ):
        connection.exec_driver_sql(
            """
                CREATE OR REPLACE FUNCTION enforce_fixed_lesson_project_integrity()
                RETURNS trigger AS $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM assignments WHERE id=NEW.assignment_id AND project_id=NEW.project_id) THEN
                        RAISE EXCEPTION 'Tiết cố định và phân công không cùng project.' USING ERRCODE='23514';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
        )
        connection.exec_driver_sql(
            "DROP TRIGGER IF EXISTS trg_fixed_lesson_project_integrity ON fixed_lessons"
        )
        connection.exec_driver_sql(
            """
                CREATE TRIGGER trg_fixed_lesson_project_integrity
                BEFORE INSERT OR UPDATE OF project_id, assignment_id
                ON fixed_lessons FOR EACH ROW
                EXECUTE FUNCTION enforce_fixed_lesson_project_integrity()
                """
        )
        invalid_fixed_lessons = connection.exec_driver_sql(
            """
                SELECT COUNT(*) FROM fixed_lessons f
                LEFT JOIN assignments a ON a.id=f.assignment_id
                WHERE a.id IS NULL OR a.project_id<>f.project_id
                """
        ).scalar()
        if invalid_fixed_lessons:
            raise RuntimeError(
                f"Phát hiện {invalid_fixed_lessons} tiết cố định có tham chiếu chéo project. "
                "Hãy sửa dữ liệu trước khi khởi động ứng dụng."
            )
