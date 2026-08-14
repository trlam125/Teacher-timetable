from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from psycopg import connect, sql
from sqlalchemy.engine import make_url


def connection_uri(url) -> str:
    """Tra ve URI PostgreSQL ma psycopg co the su dung truc tiep."""
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def main() -> int:
    load_dotenv()
    connect_timeout = max(1, int(os.getenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "10")))
    raw_url = (os.getenv("DATABASE_URL") or "").strip()
    if not raw_url:
        print("[LOI] Thieu DATABASE_URL trong file .env.", file=sys.stderr)
        return 1

    try:
        url = make_url(raw_url)
    except Exception as exc:
        print(f"[LOI] DATABASE_URL khong hop le: {exc}", file=sys.stderr)
        return 1

    if not url.drivername.startswith("postgresql"):
        print("[LOI] Project nay chi ho tro PostgreSQL.", file=sys.stderr)
        return 1

    database_name = (url.database or "").strip()
    if not database_name:
        print("[LOI] DATABASE_URL chua co ten database.", file=sys.stderr)
        return 1

    # Thu ket noi truc tiep truoc. Nho vay database da ton tai khong doi hoi
    # tai khoan phai co quyen CONNECT vao database bao tri "postgres".
    try:
        with connect(connection_uri(url), connect_timeout=connect_timeout):
            print(f"Database '{database_name}' da ton tai, bo qua buoc tao moi.")
            return 0
    except Exception:
        pass

    maintenance_database = (
        os.getenv("POSTGRES_MAINTENANCE_DB", "postgres").strip() or "postgres"
    )
    maintenance_url = url.set(database=maintenance_database)

    try:
        with connect(
            connection_uri(maintenance_url),
            autocommit=True,
            connect_timeout=connect_timeout,
        ) as connection:
            exists = connection.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (database_name,),
            ).fetchone()
            if exists:
                print(
                    f"[LOI] Database '{database_name}' co ton tai nhung khong the ket noi. "
                    "Hay kiem tra user, mat khau va quyen CONNECT trong DATABASE_URL.",
                    file=sys.stderr,
                )
                return 1

            connection.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
            )
            print(f"Da tao database '{database_name}'.")
            return 0
    except Exception as exc:
        print(
            "[LOI] Khong the kiem tra hoac tao database PostgreSQL: "
            f"{exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
