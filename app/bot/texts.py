"""Тексты сообщений бота (HTML parse mode). Все динамические значения экранируются.

Ссылки на сайт отправляются кнопками (см. handlers.py), поэтому в текстах адресов нет.
"""
from __future__ import annotations

from html import escape

from app.models import Application, Tour
from app.services.tours import format_date_range

NOT_A_BOOKING = "Заявка не является бронированием и не подтверждает наличие мест."
CATALOG_NOT_LINKED = "Каталог туров открыт на сайте Naomi Tours."


def tour_dates(tour: Tour) -> str:
    text = format_date_range(tour.start_date, tour.end_date)
    if tour.dates_are_demo:
        text += " (условные даты)"
    return text


def _with_catalog_hint(text: str, site_is_public: bool) -> str:
    """Без публичного сайта кнопки-ссылки нет — тогда хотя бы называем, где каталог."""
    return text if site_is_public else f"{text}\n\n{CATALOG_NOT_LINKED}"


def welcome(site_is_public: bool) -> str:
    return _with_catalog_hint(
        "👋 <b>Naomi Tours</b> — групповые поездки из Франкфурта и Майнца.\n\n"
        "Выберите тур на сайте и нажмите «Оставить заявку» — бот откроется уже с этим туром.",
        site_is_public,
    )


def tour_not_found(site_is_public: bool) -> str:
    return _with_catalog_hint(
        "Не нашли тур по этой ссылке — возможно, она устарела. Актуальные поездки — в каталоге.",
        site_is_public,
    )


def tour_unavailable(tour: Tour, site_is_public: bool) -> str:
    return _with_catalog_hint(
        f"Тур «{escape(tour.title)}» уже начался или завершился. Актуальные поездки — в каталоге.",
        site_is_public,
    )


def session_expired(site_is_public: bool) -> str:
    return _with_catalog_hint(
        "Эта заявка уже не активна. Откройте тур на сайте и нажмите «Оставить заявку» ещё раз.",
        site_is_public,
    )


def tour_card(tour: Tour) -> str:
    lines = [f"<b>{escape(tour.title)}</b>"]
    # Подзаголовок обычно уже перечисляет маршрут — маршрут отдельно показываем, только если его нет.
    if tour.subtitle:
        lines.append(escape(tour.subtitle))
    elif tour.route:
        lines.append(escape(" — ".join(tour.route)))
    lines.append("")
    lines.append(f"📅 {escape(tour_dates(tour))}")
    if tour.duration:
        lines.append(f"⏱ {escape(tour.duration)}")
    if tour.price_label:
        lines.append(f"💶 {escape(tour.price_label)}")
    if tour.summary:
        lines.extend(["", escape(tour.summary)])
    return "\n".join(lines)


def ask_name() -> str:
    return "Как к вам обращаться?\n<i>Напишите имя или нажмите кнопку ниже. Отменить — /cancel</i>"


def name_accepted(name: str) -> str:
    return f"Приятно познакомиться, {escape(name)}!"


def ask_comment() -> str:
    return (
        "Комментарий для организатора — например, сколько вас человек.\n"
        "<i>Можно пропустить. Паспортные и платёжные данные не нужны.</i>"
    )


def summary(tour: Tour, name: str, comment: str, username: str | None) -> str:
    lines = [
        "<b>Проверьте заявку</b>",
        "",
        f"🧳 <b>Тур:</b> {escape(tour.title)}",
        f"📅 <b>Даты:</b> {escape(tour_dates(tour))}",
        f"👤 <b>Имя:</b> {escape(name)}",
    ]
    if comment:
        lines.append(f"💬 <b>Комментарий:</b> {escape(comment)}")
    if username:
        lines.append(f"✈️ <b>Telegram:</b> @{escape(username)}")
    lines.extend(["", f"<i>{NOT_A_BOOKING} Оплата через бота не принимается.</i>"])
    return "\n".join(lines)


def application_saved(application: Application, tour: Tour, organizer_notified: bool) -> str:
    """Итог отправки: обещаем только то, что действительно произошло."""
    status = "сохранена и отправлена организатору" if organizer_notified else "сохранена"
    return "\n".join([
        f"✅ <b>Заявка №{application.id} {status}</b>",
        "",
        f"🧳 {escape(tour.title)}",
        f"📅 {escape(tour_dates(tour))}",
        "",
        f"<i>Это демонстрационная заявка. {NOT_A_BOOKING}</i>",
    ])


def admin_notification(application: Application, tour: Tour) -> str:
    username = f"@{escape(application.telegram_username)}" if application.telegram_username else "—"
    return "\n".join([
        f"🆕 <b>Демо-заявка №{application.id}</b>",
        f"🧳 {escape(tour.title)} [{escape(tour.tour_code)}]",
        f"📅 {escape(tour_dates(tour))}",
        f"👤 {escape(application.name)}",
        f"✈️ {username} (ID {application.telegram_user_id or '—'})",
        f"💬 {escape(application.comment) if application.comment else '—'}",
    ])


CANCELLED = "Заявка отменена. Чтобы начать заново, откройте тур на сайте и нажмите «Оставить заявку»."
NOTHING_TO_CANCEL = "Сейчас нет незавершённой заявки."
TEXT_EXPECTED = "Пожалуйста, отправьте текстовое сообщение."
USE_BUTTONS = "Подтвердите или отмените заявку кнопками выше. Отменить — /cancel"
