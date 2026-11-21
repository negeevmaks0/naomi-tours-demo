"""Подключение к SQLite через SQLAlchemy 2.x."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import PROJECT_ROOT


class Base(DeclarativeBase):
    pass


SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


def _ensure_sqlite_dir(database_url: str) -> None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return
    raw_path = database_url[len(prefix):]
    if not raw_path or raw_path == ":memory:":
        return
    path = Path(raw_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)


def _resolve_sqlite_url(database_url: str) -> str:
    """Относительный путь SQLite считаем от корня проекта, а не от текущей папки."""
    prefix = "sqlite:///"
    if database_url.startswith(prefix):
        raw_path = database_url[len(prefix):]
        if raw_path and raw_path != ":memory:" and not Path(raw_path).is_absolute():
            return prefix + (PROJECT_ROOT / raw_path).as_posix()
    return database_url


def init_engine(database_url: str) -> Engine:
    _ensure_sqlite_dir(database_url)
    engine = create_engine(
        _resolve_sqlite_url(database_url),
        connect_args={"check_same_thread": False},
    )
    SessionLocal.configure(bind=engine)
    return engine


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
