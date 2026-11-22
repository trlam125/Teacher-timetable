"""Run explicitly after verifying the target DB and taking a backup."""
import argparse

from .models import StudioBase


def main():
    parser = argparse.ArgumentParser(description="Create isolated AI Studio tables")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print("Tables: " + ", ".join(StudioBase.metadata.tables))
        print("After backup and DB confirmation, run with --apply.")
        return
    from app.database import engine
    if engine.dialect.name != "postgresql":
        parser.error("Production migrations require PostgreSQL.")
    with engine.begin() as connection:
        connection.exec_driver_sql("SET LOCAL lock_timeout = '8s'")
        connection.exec_driver_sql("SET LOCAL statement_timeout = '30s'")
        connection.exec_driver_sql("SELECT pg_advisory_xact_lock(73120261122)")
        StudioBase.metadata.create_all(connection)
    print("AI Studio schema is ready.")


if __name__ == "__main__":
    main()
