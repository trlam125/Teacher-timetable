from __future__ import annotations

from app.services.foundation import *
from app.services.auth import *
from app.services.projects import *

def migrate_schema():
    """Nâng cấp schema PostgreSQL và loại bỏ cấu trúc liên kết tài khoản giáo viên cũ."""
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"SET LOCAL lock_timeout = '{DATABASE_DDL_LOCK_TIMEOUT_SECONDS}s'"
        )
        connection.exec_driver_sql(
            f"SET LOCAL statement_timeout = '{DATABASE_STATEMENT_TIMEOUT_SECONDS}s'"
        )
        inspector = inspect(connection)
        if "users" not in inspector.get_table_names():
            return

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

        if "projects" in inspector.get_table_names():
            project_columns = {
                column["name"] for column in inspector.get_columns("projects")
            }
            if "school_id" not in project_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE projects ADD COLUMN school_id INTEGER"
                )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_projects_school_id ON projects (school_id)"
            )
            # Chuẩn hóa các tên trường đã có thành bảng schools. Việc gán trường
            # cho tài khoản vẫn để quản trị viên thực hiện thủ công ở Quản lý tài khoản.
            connection.exec_driver_sql(
                "INSERT INTO schools (name, created_at) "
                "SELECT DISTINCT TRIM(school_name), %s FROM projects "
                "WHERE school_name IS NOT NULL AND TRIM(school_name)<>'' "
                "ON CONFLICT (name) DO NOTHING",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"),),
            )
            connection.exec_driver_sql(
                "UPDATE projects p SET school_id=s.id FROM schools s "
                "WHERE p.school_id IS NULL AND TRIM(p.school_name)=s.name"
            )

        if "chat_messages" in inspector.get_table_names():
            chat_columns = {
                column["name"] for column in inspector.get_columns("chat_messages")
            }
            if "school_id" not in chat_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE chat_messages ADD COLUMN school_id INTEGER"
                )
            if "reply_to_id" not in chat_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE chat_messages ADD COLUMN reply_to_id INTEGER"
                )
            if "edited_at" not in chat_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE chat_messages ADD COLUMN edited_at VARCHAR(40)"
                )
            if "deleted_at" not in chat_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE chat_messages ADD COLUMN deleted_at VARCHAR(40)"
                )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_chat_messages_reply_to_id "
                "ON chat_messages (reply_to_id)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_chat_messages_school_id "
                "ON chat_messages (school_id)"
            )
        connection.exec_driver_sql(
            "UPDATE users SET role='teacher' WHERE role IS NULL OR role='' OR role IN ('user', 'pending')"
        )
        bootstrap_email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
        try:
            configured_super_admin_id = int(os.getenv("SUPER_ADMIN_USER_ID", "0") or 0)
        except ValueError:
            configured_super_admin_id = 0

        configured_super_admin_exists = False
        if configured_super_admin_id > 0:
            configured_super_admin_exists = (
                connection.exec_driver_sql(
                    "SELECT 1 FROM users WHERE id=%s",
                    (configured_super_admin_id,),
                ).first()
                is not None
            )
            if not configured_super_admin_exists:
                logger.error(
                    "SUPER_ADMIN_USER_ID=%s không tồn tại; giữ nguyên super_admin hiện tại.",
                    configured_super_admin_id,
                )

        existing_super_admin_id = connection.exec_driver_sql(
            "SELECT id FROM users WHERE role='super_admin' ORDER BY id ASC LIMIT 1"
        ).scalar()
        bootstrap_super_admin_exists = False
        # BOOTSTRAP_ADMIN_EMAIL chỉ dùng để khởi tạo/khôi phục khi database chưa
        # có super_admin. Sau khi super admin đổi email, không được tạo lại tài
        # khoản email bootstrap cũ rồi hạ quyền tài khoản hiện tại.
        if (
            configured_super_admin_id <= 0
            and existing_super_admin_id is None
            and bootstrap_email
        ):
            bootstrap_super_admin_exists = (
                connection.exec_driver_sql(
                    "SELECT 1 FROM users WHERE lower(email)=lower(%s)",
                    (bootstrap_email,),
                ).first()
                is not None
            )

        if "projects" in inspector.get_table_names():
            # Keep valid 5-7 day schedules intact. Only repair missing or
            # out-of-range legacy values so a 5-day project survives restarts.
            connection.exec_driver_sql(
                "UPDATE projects SET days=6 WHERE days IS NULL OR days<5 OR days>7"
            )

            connection.exec_driver_sql(
                "ALTER TABLE projects DROP COLUMN IF EXISTS teacher_invite_token"
            )

            # Chủ project thường giữ role admin. Chỉ hạ quyền super_admin khi
            # đã xác nhận chắc chắn tài khoản đích tồn tại; cấu hình sai không
            # được phép làm hệ thống mất toàn bộ super_admin.
            if configured_super_admin_exists:
                connection.exec_driver_sql(
                    "UPDATE users SET role='admin', is_superadmin=FALSE "
                    "WHERE id IN (SELECT DISTINCT owner_id FROM projects) AND id<>%s",
                    (configured_super_admin_id,),
                )
            elif configured_super_admin_id <= 0 and bootstrap_super_admin_exists:
                connection.exec_driver_sql(
                    "UPDATE users SET role='admin', is_superadmin=FALSE "
                    "WHERE id IN (SELECT DISTINCT owner_id FROM projects) "
                    "AND lower(email)<>lower(%s)",
                    (bootstrap_email,),
                )
            else:
                connection.exec_driver_sql(
                    "UPDATE users SET role='admin', is_superadmin=FALSE "
                    "WHERE id IN (SELECT DISTINCT owner_id FROM projects) "
                    "AND role<>'super_admin'"
                )
        if "registration_verifications" in inspector.get_table_names():
            connection.exec_driver_sql(
                "ALTER TABLE registration_verifications "
                "DROP COLUMN IF EXISTS project_id, "
                "DROP COLUMN IF EXISTS teacher_id, "
                "DROP COLUMN IF EXISTS requested_teacher_name"
            )
        if "teacher_account_links" in inspector.get_table_names():
            connection.exec_driver_sql("DROP TABLE teacher_account_links")
        # teacher_preferences được giữ lại có chủ đích như dữ liệu tham khảo.
        # Từ phiên bản này, nguyện vọng mới gắn với tài khoản đã xác minh email
        # thay vì hồ sơ Teacher, để không khôi phục cơ chế gán account -> Teacher.
        if "teacher_preferences" in inspector.get_table_names():
            preference_columns = {
                column["name"]
                for column in inspector.get_columns("teacher_preferences")
            }
            if "submitted_by_user_id" not in preference_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE teacher_preferences ADD COLUMN submitted_by_user_id INTEGER"
                )
            if "submitted_name" not in preference_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE teacher_preferences ADD COLUMN submitted_name VARCHAR(120) NOT NULL DEFAULT ''"
                )
            if "submitted_email" not in preference_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE teacher_preferences ADD COLUMN submitted_email VARCHAR(255) NOT NULL DEFAULT ''"
                )
            connection.exec_driver_sql(
                "ALTER TABLE teacher_preferences ALTER COLUMN teacher_id DROP NOT NULL"
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_teacher_preferences_submitted_by_user_id "
                "ON teacher_preferences (submitted_by_user_id)"
            )
            # Dữ liệu cũ có thể còn user_id trỏ tới tài khoản đã bị xóa.
            # Dọn các giá trị mồ côi trước khi bổ sung khóa ngoại để migration
            # chạy được trên database đang sử dụng.
            connection.exec_driver_sql(
                "UPDATE teacher_preferences preference "
                "SET submitted_by_user_id=NULL "
                "WHERE submitted_by_user_id IS NOT NULL "
                "AND NOT EXISTS ("
                "SELECT 1 FROM users WHERE users.id=preference.submitted_by_user_id"
                ")"
            )
            connection.exec_driver_sql(
                "DO $$ "
                "BEGIN "
                "IF NOT EXISTS ("
                "SELECT 1 FROM pg_constraint "
                "WHERE conname='fk_teacher_preferences_submitted_by_user_id'"
                ") THEN "
                "ALTER TABLE teacher_preferences "
                "ADD CONSTRAINT fk_teacher_preferences_submitted_by_user_id "
                "FOREIGN KEY (submitted_by_user_id) REFERENCES users(id) "
                "ON DELETE SET NULL; "
                "END IF; "
                "END $$"
            )
        # Không migrate nguyện vọng thành teacher.unavailable_json và không dùng
        # chúng làm ràng buộc xếp lịch.
        connection.exec_driver_sql(
            "ALTER TABLE users ALTER COLUMN role SET DEFAULT 'teacher'"
        )
        if configured_super_admin_exists:
            connection.exec_driver_sql(
                "UPDATE users SET role=CASE WHEN role='super_admin' THEN 'admin' ELSE role END, "
                "is_superadmin=FALSE WHERE id<>%s",
                (configured_super_admin_id,),
            )
            connection.exec_driver_sql(
                "UPDATE users SET role='super_admin', is_superadmin=TRUE WHERE id=%s",
                (configured_super_admin_id,),
            )
        elif configured_super_admin_id <= 0 and bootstrap_super_admin_exists:
            connection.exec_driver_sql(
                "UPDATE users SET role=CASE WHEN role='super_admin' THEN 'admin' ELSE role END, "
                "is_superadmin=FALSE WHERE lower(email)<>lower(%s)",
                (bootstrap_email,),
            )
            connection.exec_driver_sql(
                "UPDATE users SET role='super_admin', is_superadmin=TRUE "
                "WHERE lower(email)=lower(%s)",
                (bootstrap_email,),
            )

        connection.exec_driver_sql(
            "ALTER TABLE users "
            "DROP COLUMN IF EXISTS teacher_id, "
            "DROP COLUMN IF EXISTS requested_teacher_name, "
            "DROP COLUMN IF EXISTS requested_project_id"
        )

        # Từ phiên bản này, môn giáo viên có thể dạy được lưu riêng. Với dữ
        # liệu cũ, suy ra quan hệ này từ các phân công đã tồn tại để nâng cấp
        # không làm mất khả năng chỉnh sửa/xếp lịch của project hiện hữu.
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

        # Block-based scheduling migration. From this version onward every Lesson
        # has a persistent block_id. required_double blocks are migrated once by
        # deterministically partitioning each legacy contiguous run from left to
        # right into pairs plus a possible single. Runtime operations never infer
        # blocks from adjacency again.
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

                legacy_rows = connection.exec_driver_sql(
                    "SELECT a.id AS assignment_id, p.sessions, p.periods_per_session, "
                    "l.id AS lesson_id, l.slot "
                    "FROM assignments a "
                    "JOIN projects p ON p.id=a.project_id "
                    "JOIN lessons l ON l.assignment_id=a.id "
                    "WHERE a.block_mode='required_double' AND l.block_id IS NULL "
                    "ORDER BY a.id, l.slot, l.id"
                ).mappings().all()
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
                        if (
                            current
                            and (key != previous_key or slot != previous_slot + 1)
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
                            for row in run[index:index + size]:
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

        # Khóa tính toàn vẹn project ở tầng PostgreSQL. Các FK đơn chỉ chứng
        # minh bản ghi liên quan tồn tại, nhưng không chứng minh chúng thuộc
        # cùng project. Trigger dưới đây chặn dữ liệu chéo project kể cả khi
        # import trực tiếp hoặc có endpoint mới bỏ sót validation ứng dụng.
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

        if "fixed_lessons" in inspector.get_table_names() and "assignments" in inspector.get_table_names():
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

        # Bảo vệ bất biến ở tầng PostgreSQL: tại một project/slot, một giáo
        # viên hoặc một lớp chỉ được xuất hiện trong tối đa một Lesson. Lesson
        # chỉ lưu assignment_id nên không thể diễn đạt hai UNIQUE constraint này
        # trực tiếp; trigger tra Assignment và dùng advisory lock theo project/slot
        # để cả import trực tiếp hoặc hai transaction đồng thời cũng không lọt.
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

        # Bản demo rất cũ từng được tạo chỉ với một buổi. Đây là migration
        # thay đổi dữ liệu nên tuyệt đối không nhận diện project bằng tên/trường:
        # người dùng có thể tạo project thật trùng các giá trị đó. Chỉ migrate
        # các project_id được quản trị viên chỉ định rõ qua biến môi trường, và
        # lưu marker theo từng project để migration không thể chạy lặp.
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

def acquire_database_bootstrap_lock(lock_connection):
    deadline = time.monotonic() + DATABASE_BOOTSTRAP_LOCK_TIMEOUT_SECONDS
    while True:
        acquired = bool(
            lock_connection.exec_driver_sql(
                "SELECT pg_try_advisory_lock(%s)",
                (DATABASE_BOOTSTRAP_LOCK_KEY,),
            ).scalar()
        )
        if acquired:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(
                "Không thể lấy khóa khởi tạo database trong thời gian cho phép."
            )
        time.sleep(min(0.25, remaining))

def run_database_bootstrap_step(callback):
    """Tuần tự hóa các bước DDL/bootstrap giữa nhiều process cùng dùng một PostgreSQL."""
    with engine.connect() as lock_connection:
        acquire_database_bootstrap_lock(lock_connection)
        try:
            return callback()
        finally:
            try:
                lock_connection.exec_driver_sql(
                    "SELECT pg_advisory_unlock(%s)",
                    (DATABASE_BOOTSTRAP_LOCK_KEY,),
                )
            except Exception:
                pass

def initialize_schema():
    with engine.begin() as schema_connection:
        schema_connection.exec_driver_sql(
            f"SET LOCAL lock_timeout = '{DATABASE_DDL_LOCK_TIMEOUT_SECONDS}s'"
        )
        schema_connection.exec_driver_sql(
            f"SET LOCAL statement_timeout = '{DATABASE_STATEMENT_TIMEOUT_SECONDS}s'"
        )
        Base.metadata.create_all(schema_connection)
    migrate_schema()

def seed_project(db: Session, p: Project):
    d1 = Department(project_id=p.id, name="Tổ Toán - Tin")
    d2 = Department(project_id=p.id, name="Tổ Ngữ văn")
    db.add_all([d1, d2])
    db.flush()
    s1 = Subject(project_id=p.id, name="Toán", short_name="TOÁN", max_consecutive=2)
    s2 = Subject(project_id=p.id, name="Ngữ văn", short_name="VĂN", max_consecutive=2)
    s3 = Subject(project_id=p.id, name="Tin học", short_name="TIN", max_consecutive=1)
    db.add_all([s1, s2, s3])
    db.flush()
    t1 = Teacher(
        project_id=p.id,
        department_id=d1.id,
        name="Nguyễn Văn An",
        short_name="An",
        max_periods_day=4,
    )
    t2 = Teacher(
        project_id=p.id,
        department_id=d2.id,
        name="Trần Thị Bình",
        short_name="Bình",
        max_periods_day=4,
    )
    t3 = Teacher(
        project_id=p.id,
        department_id=d1.id,
        name="Lê Minh Châu",
        short_name="Châu",
        max_periods_day=4,
    )
    db.add_all([t1, t2, t3])
    db.flush()
    db.add_all(
        [
            TeacherSubject(project_id=p.id, teacher_id=t1.id, subject_id=s1.id),
            TeacherSubject(project_id=p.id, teacher_id=t2.id, subject_id=s2.id),
            TeacherSubject(project_id=p.id, teacher_id=t3.id, subject_id=s3.id),
        ]
    )
    g = Grade(project_id=p.id, name="Khối 10")
    db.add(g)
    db.flush()
    c1 = SchoolClass(project_id=p.id, grade_id=g.id, name="10A1")
    c2 = SchoolClass(project_id=p.id, grade_id=g.id, name="10A2")
    db.add_all([c1, c2])
    db.flush()
    for c in [c1, c2]:
        db.add_all(
            [
                Assignment(
                    project_id=p.id,
                    class_id=c.id,
                    subject_id=s1.id,
                    teacher_id=t1.id,
                    periods_per_week=4,
                ),
                Assignment(
                    project_id=p.id,
                    class_id=c.id,
                    subject_id=s2.id,
                    teacher_id=t2.id,
                    periods_per_week=3,
                ),
                Assignment(
                    project_id=p.id,
                    class_id=c.id,
                    subject_id=s3.id,
                    teacher_id=t3.id,
                    periods_per_week=2,
                ),
            ]
        )
    db.commit()

def ensure_demo():
    db = SessionLocal()
    try:
        existing_super_admin = db.scalar(
            select(User)
            .where(User.role == "super_admin")
            .order_by(User.id.asc())
            .limit(1)
        )
        configured_target = (
            db.get(User, SUPER_ADMIN_USER_ID) if SUPER_ADMIN_USER_ID > 0 else None
        )
        if SUPER_ADMIN_USER_ID > 0 and configured_target is None:
            logger.error(
                "SUPER_ADMIN_USER_ID=%s không tồn tại; không hạ quyền super_admin hiện tại.",
                SUPER_ADMIN_USER_ID,
            )
            if existing_super_admin is not None:
                return

        email_target = (
            db.scalar(
                select(User)
                .where(func.lower(User.email) == BOOTSTRAP_ADMIN_EMAIL)
                .limit(1)
            )
            if BOOTSTRAP_ADMIN_EMAIL
            else None
        )
        target = (
            configured_target
            if configured_target is not None
            else (existing_super_admin or email_target)
        )

        if target is not None and target.role == "super_admin":
            changed = not bool(target.is_superadmin)
            target.is_superadmin = True
            for other in db.scalars(
                select(User).where(User.role == "super_admin", User.id != target.id)
            ).all():
                other.role = "admin"
                other.is_superadmin = False
                changed = True
            if changed:
                db.commit()
            return

        if target is None and (
            not BOOTSTRAP_ADMIN_EMAIL or len(BOOTSTRAP_ADMIN_PASSWORD) < 8
        ):
            if existing_super_admin is not None:
                return
            raise RuntimeError(
                "Database chưa có super admin. Hãy cấu hình SUPER_ADMIN_USER_ID trỏ tới "
                "một tài khoản tồn tại hoặc cấu hình BOOTSTRAP_ADMIN_EMAIL và "
                "BOOTSTRAP_ADMIN_PASSWORD (ít nhất 8 ký tự) để khôi phục quyền quản trị."
            )

        user = target
        if user is None:
            user = User(
                email=BOOTSTRAP_ADMIN_EMAIL,
                name="Quản trị viên",
                password_hash=pwd.hash(BOOTSTRAP_ADMIN_PASSWORD),
                role="super_admin",
                is_superadmin=True,
            )
            db.add(user)
            db.flush()
        else:
            user.role = "super_admin"
            user.is_superadmin = True
            if BOOTSTRAP_ADMIN_EMAIL and len(BOOTSTRAP_ADMIN_PASSWORD) >= 8:
                user.password_hash = pwd.hash(BOOTSTRAP_ADMIN_PASSWORD)
                user.session_version = max(1, user.session_version or 1) + 1
            if not (user.name or "").strip():
                user.name = "Quản trị viên"

        # Chỉ hạ các super_admin khác sau khi tài khoản đích đã tồn tại trong
        # transaction hiện tại. Nhờ vậy cấu hình sai không thể làm mất quyền.
        for other in db.scalars(
            select(User).where(User.role == "super_admin", User.id != user.id)
        ).all():
            other.role = "admin"
            other.is_superadmin = False

        db.commit()
        if SEED_DEMO_DATA and db.scalar(select(Project.id).limit(1)) is None:
            school = ensure_school_for_name(db, "THPT Demo")
            p = Project(
                owner_id=user.id,
                school_id=school.id,
                name="TKB học kỳ I",
                school_name=school.name,
                days=6,
                sessions=2,
                periods_per_session=5,
            )
            db.add(p)
            db.commit()
            seed_project(db, p)
    finally:
        db.close()

def initialize_database():
    initialize_schema()
    ensure_demo()


__all__ = [name for name in globals() if not name.startswith('__')]
