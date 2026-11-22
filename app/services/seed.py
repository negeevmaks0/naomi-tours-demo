"""Создание таблиц и загрузка туров из data/seed_tours.json (upsert по tour_code)."""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session

from app.config import SEED_PATH
from app.database import Base
from app.models import Tour

logger = logging.getLogger(__name__)

_DATE_FIELDS = ("start_date", "end_date")


def load_seed_records(path: Path = SEED_PATH) -> list[dict]:
    """Читает seed и раскрывает записи с copy_from (наследование содержимого)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    by_code: dict[str, dict] = {}
    records: list[dict] = []
    for item in raw["tours"]:
        record = dict(item)
        base_code = record.pop("copy_from", None)
        if base_code is not None:
            if base_code not in by_code:
                raise ValueError(f"copy_from ссылается на неизвестный тур: {base_code}")
            record = {**by_code[base_code], **record}
        record.setdefault("listed", True)
        for field in _DATE_FIELDS:
            record[field] = date.fromisoformat(record[field])
        if record["end_date"] < record["start_date"]:
            raise ValueError(f"У тура {record['tour_code']} дата окончания раньше начала")
        if record["tour_code"] in by_code:
            raise ValueError(f"Повторяющийся tour_code: {record['tour_code']}")
        by_code[record["tour_code"]] = record
        records.append(record)
    return records


def seed_tours(session: Session, records: list[dict]) -> None:
    """Добавляет новые туры из seed и обновляет нетронутые; туры, изменённые в админке, не трогает."""
    for record in records:
        tour = session.scalar(select(Tour).where(Tour.tour_code == record["tour_code"]))
        if tour is None:
            session.add(Tour(**record, source="seed"))
        elif tour.source == "seed":
            for key, value in record.items():
                setattr(tour, key, value)


# Колонки, добавленные после первой версии схемы: таблица -> {имя: DDL для ALTER TABLE}.
_ADDED_COLUMNS = {
    "tours": {
        "listed": "BOOLEAN NOT NULL DEFAULT 1",
        "forum_topic_id": "INTEGER",
        "announcement_message_id": "INTEGER",
        "source": "VARCHAR(16) NOT NULL DEFAULT 'seed'",
    },
    "applications": {
        "decided_at": "DATETIME",
        "invite_link": "VARCHAR(200)",
        "invite_error": "VARCHAR(300)",
    },
}


def _add_missing_columns(engine: Engine) -> None:
    """Минимальная миграция для уже существующей локальной SQLite-базы."""
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            existing = {col["name"] for col in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    logger.info("Added column %s.%s", table, name)
        # Статус заявок первой версии.
        conn.execute(text("UPDATE applications SET status = 'new' WHERE status = 'demo_new'"))


def init_db(engine: Engine, seed_path: Path = SEED_PATH) -> None:
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    records = load_seed_records(seed_path)
    with Session(engine) as session:
        seed_tours(session, records)
        session.commit()
    logger.info("Database ready, tours in seed: %d", len(records))
