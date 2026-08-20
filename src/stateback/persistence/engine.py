from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def require_database_url() -> str:
    file_path = os.environ.get("STATEBACK_DATABASE_URL_FILE")
    if file_path is not None:
        try:
            url = Path(file_path).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise RuntimeError("STATEBACK_DATABASE_URL_FILE cannot be read") from exc
        if not url or len(url) > 4096 or "\n" in url:
            raise RuntimeError(
                "STATEBACK_DATABASE_URL_FILE must contain one bounded database URL"
            )
        return url
    env_url = os.environ.get("STATEBACK_DATABASE_URL")
    if not env_url:
        raise RuntimeError("STATEBACK_DATABASE_URL is required")
    return env_url


def create_engine_from_url(url: str) -> Engine:
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
    )


def create_engine_from_env() -> Engine:
    return create_engine_from_url(require_database_url())


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=True,
        class_=Session,
    )
