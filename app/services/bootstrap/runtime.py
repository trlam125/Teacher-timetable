from __future__ import annotations

from app.services.foundation import *
from app.services.auth import *
from app.services.projects import *

from .schema import migrate_schema
from .demo import ensure_demo


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


def initialize_database():
    initialize_schema()
    ensure_demo()


__all__ = [name for name in globals() if not name.startswith("__")]
