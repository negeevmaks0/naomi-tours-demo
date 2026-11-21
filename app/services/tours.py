"""Поиск туров, публичная выдача и deep link на бота."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import Enum
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Tour

# Telegram допускает в start-параметре только A-Z, a-z, 0-9, _ и -, до 64 символов.
TOUR_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_MONTHS_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def current_date() -> date:
    """Единая точка получения «сегодня» (подменяется в тестах)."""
    return date.today()


def is_valid_tour_code(code: str) -> bool:
    return bool(TOUR_CODE_RE.fullmatch(code))


def list_public_tours(session: Session, today: date) -> list[Tour]:
    stmt = (
        select(Tour)
        .where(Tour.start_date > today, Tour.listed.is_(True))
        .order_by(Tour.start_date, Tour.id)
    )
    return list(session.scalars(stmt))


def get_tour_by_code(session: Session, code: str) -> Tour | None:
    if not is_valid_tour_code(code):
        return None
    return session.scalar(select(Tour).where(Tour.tour_code == code))


class LookupStatus(str, Enum):
    OK = "ok"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class TourLookup:
    status: LookupStatus
    tour: Tour | None = None


def find_public_tour(session: Session, code: str, today: date) -> TourLookup:
    tour = get_tour_by_code(session, code.strip())
    if tour is None:
        return TourLookup(LookupStatus.NOT_FOUND)
    if not tour.is_public(today):
        return TourLookup(LookupStatus.UNAVAILABLE, tour)
    return TourLookup(LookupStatus.OK, tour)


def build_start_link(bot_username: str, tour_code: str) -> str | None:
    """Ссылка https://t.me/<bot>?start=<code>; None, если имя бота не задано."""
    username = bot_username.strip().lstrip("@")
    if not username:
        return None
    if not is_valid_tour_code(tour_code):
        raise ValueError(f"Недопустимый tour_code для deep link: {tour_code!r}")
    return f"https://t.me/{quote(username)}?start={tour_code}"


def format_date_range(start: date, end: date) -> str:
    if start.year == end.year and start.month == end.month:
        return f"{start.day}–{end.day} {_MONTHS_GENITIVE[end.month - 1]} {end.year}"
    if start.year == end.year:
        return (f"{start.day} {_MONTHS_GENITIVE[start.month - 1]} — "
                f"{end.day} {_MONTHS_GENITIVE[end.month - 1]} {end.year}")
    return (f"{start.day} {_MONTHS_GENITIVE[start.month - 1]} {start.year} — "
            f"{end.day} {_MONTHS_GENITIVE[end.month - 1]} {end.year}")
