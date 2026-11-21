"""Тексты сообщений бота (HTML parse mode). Все динамические значения экранируются."""
from __future__ import annotations

from html import escape

from app.config import Settings
from app.models import Application, Tour
from app.services.tours import format_date_range

DEMO_DISCLAIMER = (
    "ℹ️ Это демонстрационная заявка: она не подтверждает бронирование и наличие мест. "
    "Оплата через бота не принимается."
)


def tour_dates(tour: Tour) -> str:
    text = format_date_range(tour.start_date, tour.end_date)
    if tour.dates_are_demo:
        text += " (условные демонстрационные даты)"
    return text


def _catalog_line(settings: Settings, prefix: str) -> str:
    """Ссылку на каталог отправляем, только если сайт доступен не только с этого компьютера."""
    if settings.site_is_public:
        return f"{prefix}: {escape(settings.catalog_url)}"
    return "Каталог туров открыт на сайте Naomi Tours."


def welcome(settings: Settings) -> str:
    return (
        "Здравствуйте! Это бот Naomi Tours для заявок на групповые поездки.\n\n"
        "Выберите тур в каталоге на сайте и нажмите «Оставить заявку» — "
        "бот откроется уже с выбранной поездкой.\n\n"
        + _catalog_line(settings, "Каталог")
    )


def tour_not_found(settings: Settings) -> str:
    return (
        "Не удалось найти тур по этой ссылке. Возможно, она устарела.\n\n"
        + _catalog_line(settings, "Актуальные туры — в каталоге")
    )


def tour_unavailable(tour: Tour, settings: Settings) -> str:
    return (
        f"Тур «{escape(tour.title)}» уже начался или завершился, заявки на него не принимаются.\n\n"
        + _catalog_line(settings, "Актуальные туры — в каталоге")
    )


def session_expired(settings: Settings) -> str:
    text = "Эта заявка уже не активна. Откройте тур на сайте и нажмите «Оставить заявку» ещё раз."
    if settings.site_is_public:
        text += f"\n\nКаталог: {escape(settings.catalog_url)}"
    return text


def tour_card(tour: Tour, settings: Settings) -> str:
    lines = [f"<b>{escape(tour.title)}</b>"]
    if tour.subtitle:
        lines.append(escape(tour.subtitle))
    lines.append("")
    lines.append(f"📅 {escape(tour_dates(tour))}")
    if tour.duration:
        lines.append(f"⏱ {escape(tour.duration)}")
    if tour.price_label:
        lines.append(f"💰 {escape(tour.price_label)}")
    if tour.route:
        lines.append(f"📍 {escape(' — '.join(tour.route))}")
    if tour.summary:
        lines.extend(["", escape(tour.summary)])
    if settings.site_is_public:
        lines.extend(["", f"Подробнее на сайте: {escape(settings.tour_url(tour.tour_code))}"])
    return "\n".join(lines)


def ask_name() -> str:
    return (
        "Как к вам обращаться? Напишите имя (или нажмите кнопку с именем из Telegram).\n"
        "Отменить заявку: /cancel"
    )


def ask_comment() -> str:
    return (
        "Добавьте комментарий, если нужно (например, сколько человек или вопрос организатору). "
        "Или нажмите «Пропустить».\n"
        "Пожалуйста, не отправляйте паспортные, платёжные и другие личные данные."
    )


def summary(tour: Tour, name: str, comment: str, username: str | None) -> str:
    lines = [
        "<b>Проверьте заявку</b>",
        "",
        f"Тур: {escape(tour.title)}",
        f"Даты: {escape(tour_dates(tour))}",
        f"Имя: {escape(name)}",
        f"Комментарий: {escape(comment) if comment else '—'}",
        f"Telegram: {('@' + escape(username)) if username else 'username не указан'}",
        "",
        DEMO_DISCLAIMER,
    ]
    return "\n".join(lines)


def application_saved(application: Application, organizer_notified: bool) -> str:
    """Итог отправки: обещаем только то, что действительно произошло."""
    if organizer_notified:
        first = f"✅ Заявка №{application.id} сохранена и отправлена организатору."
    else:
        first = f"✅ Заявка №{application.id} сохранена."
    return (
        f"{first}\n\n"
        "Это демонстрационная заявка, она не является бронированием и не подтверждает наличие мест."
    )


def admin_notification(application: Application, tour: Tour) -> str:
    username = f"@{escape(application.telegram_username)}" if application.telegram_username else "—"
    return "\n".join([
        f"🆕 Демо-заявка №{application.id}",
        f"Тур: {escape(tour.title)} [{escape(tour.tour_code)}]",
        f"Даты: {escape(tour_dates(tour))}",
        f"Имя: {escape(application.name)}",
        f"Telegram: {username} (ID {application.telegram_user_id or '—'})",
        f"Комментарий: {escape(application.comment) if application.comment else '—'}",
    ])


CANCELLED = "Заявка отменена. Чтобы начать заново, откройте тур на сайте и нажмите «Оставить заявку»."
NOTHING_TO_CANCEL = "Сейчас нет незавершённой заявки."
TEXT_EXPECTED = "Пожалуйста, отправьте текстовое сообщение."
USE_BUTTONS = "Пожалуйста, подтвердите или отмените заявку кнопками ниже. Отменить: /cancel"
