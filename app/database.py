from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import DATABASE_CONNECT_TIMEOUT_SECONDS, DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_timeout=DATABASE_CONNECT_TIMEOUT_SECONDS,
    connect_args={"connect_timeout": DATABASE_CONNECT_TIMEOUT_SECONDS},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
DATABASE_BOOTSTRAP_LOCK_KEY = 73120260903
