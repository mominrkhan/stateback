from __future__ import annotations

import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def require_database_url() -> str:
    url = os.environ.get("STATEBACK_DATABASE_URL")
    if not url:
        raise RuntimeError("STATEBACK_DATABASE_URL is required")
    return url


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
