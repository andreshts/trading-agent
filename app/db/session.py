from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.base import Base


settings = get_settings()

# Normalize DATABASE_URL to use the psycopg3 driver prefix expected by SQLAlchemy.
# Cloud providers (Railway, DigitalOcean, etc.) often inject plain "postgres://" or
# "postgresql://" URLs, which map to psycopg2. We replace them so SQLAlchemy picks
# up the psycopg3 driver that is declared in pyproject.toml.
_raw_url = str(settings.database_url)
if _raw_url.startswith("postgres://"):
    _raw_url = "postgresql+psycopg://" + _raw_url[len("postgres://"):]
elif _raw_url.startswith("postgresql://"):
    _raw_url = "postgresql+psycopg://" + _raw_url[len("postgresql://"):]

connect_args = {"check_same_thread": False} if _raw_url.startswith("sqlite") else {}
engine = create_engine(_raw_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    from app.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

