from __future__ import annotations

from app.config import DATABASE_DDL_LOCK_TIMEOUT_SECONDS, DATABASE_STATEMENT_TIMEOUT_SECONDS
from app.database import engine
from app.services.bootstrap.migrations.account_roles import migrate_account_roles
from app.services.bootstrap.migrations.accounts import migrate_accounts
from app.services.bootstrap.migrations.curriculum import migrate_curriculum
from app.services.bootstrap.migrations.entity_integrity import migrate_entity_integrity
from app.services.bootstrap.migrations.legacy_projects import migrate_legacy_projects
from app.services.bootstrap.migrations.lesson_blocks import migrate_lesson_blocks
from app.services.bootstrap.migrations.lesson_integrity import migrate_lesson_integrity
from app.services.bootstrap.migrations.schools_and_chat import migrate_schools_and_chat
from sqlalchemy import inspect


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

        migrate_accounts(connection, inspector)
        migrate_schools_and_chat(connection, inspector)
        migrate_account_roles(connection, inspector)
        migrate_curriculum(connection, inspector)
        migrate_lesson_blocks(connection, inspector)
        migrate_entity_integrity(connection, inspector)
        migrate_lesson_integrity(connection, inspector)
        migrate_legacy_projects(connection, inspector)
