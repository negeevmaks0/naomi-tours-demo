"""Валидация и сохранение демонстрационных заявок."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Application, Tour

NAME_MIN_LEN = 2
NAME_MAX_LEN = 100
COMMENT_MAX_LEN = 500


class ApplicationValidationError(ValueError):
    pass


def normalize_name(raw: str | None) -> str:
    name = " ".join((raw or "").split())
    if len(name) < NAME_MIN_LEN:
        raise ApplicationValidationError(f"Имя должно содержать минимум {NAME_MIN_LEN} символа.")
    if len(name) > NAME_MAX_LEN:
        raise ApplicationValidationError(f"Имя слишком длинное (максимум {NAME_MAX_LEN} символов).")
    if not any(ch.isalpha() for ch in name):
        raise ApplicationValidationError("Имя должно содержать буквы.")
    return name


def normalize_comment(raw: str | None) -> str:
    comment = (raw or "").strip()
    if len(comment) > COMMENT_MAX_LEN:
        raise ApplicationValidationError(
            f"Комментарий слишком длинный (максимум {COMMENT_MAX_LEN} символов)."
        )
    return comment


def create_application(
    session: Session,
    tour: Tour,
    name: str,
    comment: str = "",
    telegram_user_id: int | None = None,
    telegram_username: str | None = None,
) -> Application:
    application = Application(
        tour_id=tour.id,
        name=normalize_name(name),
        comment=normalize_comment(comment),
        telegram_user_id=telegram_user_id,
        telegram_username=telegram_username or None,
    )
    session.add(application)
    session.flush()
    return application
