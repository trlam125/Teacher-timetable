from __future__ import annotations




def migrate_lesson_integrity(connection, inspector):
    if (
        "lessons" in inspector.get_table_names()
        and "assignments" in inspector.get_table_names()
    ):
        invalid_lessons = connection.exec_driver_sql(
            """
                SELECT COUNT(*) FROM lessons l
                LEFT JOIN assignments a ON a.id=l.assignment_id
                WHERE a.id IS NULL OR a.project_id<>l.project_id
                """
        ).scalar()
        if invalid_lessons:
            raise RuntimeError(
                f"Phát hiện {invalid_lessons} tiết học có tham chiếu chéo project. "
                "Hãy sửa dữ liệu trước khi khởi động ứng dụng."
            )
        connection.exec_driver_sql(
            """
                CREATE OR REPLACE FUNCTION enforce_lesson_timetable_conflict()
                RETURNS trigger AS $$
                DECLARE
                    new_teacher_id INTEGER;
                    new_class_id INTEGER;
                    assignment_project_id INTEGER;
                BEGIN
                    SELECT teacher_id, class_id, project_id
                    INTO new_teacher_id, new_class_id, assignment_project_id
                    FROM assignments
                    WHERE id = NEW.assignment_id;

                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'Phân công %% không tồn tại.', NEW.assignment_id
                            USING ERRCODE = '23503';
                    END IF;

                    IF assignment_project_id <> NEW.project_id THEN
                        RAISE EXCEPTION 'Lesson và phân công không cùng project.'
                            USING ERRCODE = '23514';
                    END IF;

                    PERFORM pg_advisory_xact_lock(NEW.project_id, NEW.slot);

                    IF EXISTS (
                        SELECT 1
                        FROM lessons l
                        JOIN assignments a ON a.id = l.assignment_id
                        WHERE l.project_id = NEW.project_id
                          AND l.slot = NEW.slot
                          AND l.id <> COALESCE(NEW.id, -1)
                          AND a.teacher_id = new_teacher_id
                    ) THEN
                        RAISE EXCEPTION 'Giáo viên đã có tiết khác tại slot %%.', NEW.slot
                            USING ERRCODE = '23505';
                    END IF;

                    IF EXISTS (
                        SELECT 1
                        FROM lessons l
                        JOIN assignments a ON a.id = l.assignment_id
                        WHERE l.project_id = NEW.project_id
                          AND l.slot = NEW.slot
                          AND l.id <> COALESCE(NEW.id, -1)
                          AND a.class_id = new_class_id
                    ) THEN
                        RAISE EXCEPTION 'Lớp đã có tiết khác tại slot %%.', NEW.slot
                            USING ERRCODE = '23505';
                    END IF;

                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
        )
        connection.exec_driver_sql(
            "DROP TRIGGER IF EXISTS trg_lesson_timetable_conflict ON lessons"
        )
        connection.exec_driver_sql(
            """
                CREATE TRIGGER trg_lesson_timetable_conflict
                BEFORE INSERT OR UPDATE OF project_id, assignment_id, slot
                ON lessons
                FOR EACH ROW
                EXECUTE FUNCTION enforce_lesson_timetable_conflict()
                """
        )
