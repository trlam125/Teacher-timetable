from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY")

if not DATABASE_URL:
    raise RuntimeError(
        "Thiếu DATABASE_URL. Hãy tạo file .env dựa trên .env.example "
        "và nhập chuỗi kết nối PostgreSQL."
    )
if not DATABASE_URL.startswith(("postgresql://", "postgresql+psycopg://")):
    raise RuntimeError("Project này chỉ hỗ trợ PostgreSQL.")
if not SECRET_KEY:
    raise RuntimeError("Thiếu SECRET_KEY. Hãy tạo khóa bí mật và thêm vào file .env.")

if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

DATABASE_CONNECT_TIMEOUT_SECONDS = 10
DATABASE_BOOTSTRAP_LOCK_TIMEOUT_SECONDS = 15
DATABASE_DDL_LOCK_TIMEOUT_SECONDS = 8
DATABASE_STATEMENT_TIMEOUT_SECONDS = 30
