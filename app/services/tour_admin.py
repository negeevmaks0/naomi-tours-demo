"""Добавление и изменение туров из админки: проверка формы, код тура, фото."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import UPLOADS_DIR
from app.models import Tour

TRANSPORTS = ("Автобус", "Авиа")
MAX_PHOTO_BYTES = 10 * 1024 * 1024
PHOTO_MAX_SIDE = 1600

_TRANSLIT = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s",
     "t", "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"],
))


class TourFormError(ValueError):
    pass


@dataclass
class TourForm:
    """Поля формы в том виде, как их вводит владелец."""
    title: str = ""
    destination: str = ""
    start_date: str = ""
    end_date: str = ""
    dates_are_demo: bool = False
    transport: str = "Автобус"
    duration: str = ""
    price_label: str = ""
    subtitle: str = ""
    summary: str = ""
    program: str = ""
    included: str = ""
    extras: str = ""
    listed: bool = True
    errors: list[str] = field(default_factory=list)

    @classmethod
    def from_tour(cls, tour: Tour) -> "TourForm":
        return cls(
            title=tour.title, destination=tour.destination,
            start_date=tour.start_date.isoformat(), end_date=tour.end_date.isoformat(),
            dates_are_demo=tour.dates_are_demo, transport=tour.transport or "Автобус",
            duration=tour.duration, price_label=tour.price_label, subtitle=tour.subtitle,
            summary=tour.summary, program=program_to_text(tour.program),
            included="\n".join(tour.included), extras="\n".join(tour.extras), listed=tour.listed,
        )


def _lines(text: str) -> list[str]:
    return [line.strip(" -•\t") for line in text.splitlines() if line.strip(" -•\t")]


def program_from_text(text: str) -> list[dict]:
    """Каждая строка — пункт программы; «Заголовок: описание» делится на две части."""
    items = []
    for line in _lines(text):
        title, sep, rest = line.partition(":")
        if sep and title and len(title) <= 80:
            items.append({"title": title.strip(), "text": rest.strip()})
        else:
            items.append({"title": line, "text": ""})
    return items


def program_to_text(program: list[dict]) -> str:
    return "\n".join(f"{p['title']}: {p['text']}" if p.get("text") else p["title"] for p in program)


def validate(form: TourForm) -> dict:
    """Проверяет форму и возвращает поля модели Tour. Ошибки — понятным языком."""
    errors = []
    for value, label in [(form.title, "название"), (form.destination, "страну"),
                         (form.price_label, "цену")]:
        if not value.strip():
            errors.append(f"Укажите {label}.")
    start = end = None
    try:
        start = date.fromisoformat(form.start_date)
        end = date.fromisoformat(form.end_date)
    except ValueError:
        errors.append("Укажите даты начала и окончания.")
    if start and end and end < start:
        errors.append("Дата окончания раньше даты начала.")
    if form.transport not in TRANSPORTS:
        errors.append("Выберите транспорт.")
    if len(form.title) > 200:
        errors.append("Название слишком длинное (до 200 символов).")
    if errors:
        raise TourFormError(" ".join(errors))
    return {
        "title": form.title.strip(),
        "destination": form.destination.strip(),
        "start_date": start,
        "end_date": end,
        "dates_are_demo": form.dates_are_demo,
        "transport": form.transport,
        "duration": form.duration.strip(),
        "price_label": form.price_label.strip(),
        "subtitle": form.subtitle.strip(),
        "summary": form.summary.strip(),
        "program": program_from_text(form.program),
        "included": _lines(form.included),
        "extras": _lines(form.extras),
        "listed": form.listed,
    }


def make_tour_code(session: Session, destination: str, start: date) -> str:
    """Стабильный код для ссылки в Telegram: латиница, цифры и «_», уникальный."""
    slug = "".join(_TRANSLIT.get(ch, ch) for ch in destination.lower())
    slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")[:30] or "tour"
    base = f"{slug}_{start:%Y_%m}"
    code, n = base, 2
    while session.scalar(select(Tour.id).where(Tour.tour_code == code)) is not None:
        code, n = f"{base}_{n}", n + 1
    return code


def save_photo(data: bytes, tour_code: str) -> str:
    """Сохраняет фото тура (уменьшенное, JPEG) и возвращает путь для Tour.image."""
    if len(data) > MAX_PHOTO_BYTES:
        raise TourFormError("Фото больше 10 МБ — выберите файл поменьше.")
    try:
        image = Image.open(io.BytesIO(data))
        image = image.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise TourFormError("Не удалось прочитать фото. Подойдут JPG или PNG.") from exc
    image.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE))
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    image.save(UPLOADS_DIR / f"{tour_code}.jpg", quality=82, optimize=True, progressive=True)
    return f"images/uploads/{tour_code}.jpg"
