"""Действия в демо-группе Telegram: темы туров, анонсы и личные приглашения.

Вызываются из админки (веб-процесс) через Bot API. Бот должен быть администратором группы
с правами «Управление темами» и «Пригласительные ссылки».
"""
from __future__ import annotations

import logging
from html import escape

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from app.config import STATIC_DIR, Settings
from app.models import Application, Tour
from app.services.tours import build_start_link, format_date_range

logger = logging.getLogger(__name__)

TOPIC_NAME_LIMIT = 128
CAPTION_LIMIT = 1024


def make_bot(settings: Settings) -> Bot:
    return Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def topic_name(tour: Tour) -> str:
    name = f"{tour.title} · {format_date_range(tour.start_date, tour.end_date)}"
    return name if len(name) <= TOPIC_NAME_LIMIT else name[: TOPIC_NAME_LIMIT - 1] + "…"


def topic_link(chat_id: int, topic_id: int | None) -> str | None:
    """Ссылка на тему супергруппы: https://t.me/c/<id без -100>/<тема>."""
    raw = str(chat_id)
    if topic_id is None or not raw.startswith("-100"):
        return None
    return f"https://t.me/c/{raw[4:]}/{topic_id}"


async def create_tour_topic(bot: Bot, chat_id: int, tour: Tour) -> int:
    topic = await bot.create_forum_topic(chat_id, name=topic_name(tour))
    return topic.message_thread_id


def announcement_text(tour: Tour) -> str:
    dates = format_date_range(tour.start_date, tour.end_date)
    if tour.dates_are_demo:
        dates += " (условные даты)"
    lines = ["🆕 <b>Новый тур</b>", "", f"<b>{escape(tour.title)}</b>"]
    if tour.subtitle:
        lines.append(escape(tour.subtitle))
    lines.extend(["", f"📅 {escape(dates)}"])
    if tour.price_label:
        lines.append(f"💶 {escape(tour.price_label)}")
    if tour.summary:
        lines.extend(["", escape(tour.summary)])
    return "\n".join(lines)


async def announce_tour(bot: Bot, chat_id: int, tour: Tour, settings: Settings) -> int:
    """Пост в общую тему группы с фото (если есть) и кнопкой «Оставить заявку»."""
    link = build_start_link(settings.bot_username, tour.tour_code)
    markup = None
    if link:
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📝 Оставить заявку", url=link)]])
    text = announcement_text(tour)
    photo = STATIC_DIR / tour.image if tour.image else None
    if photo is not None and photo.is_file() and len(text) <= CAPTION_LIMIT:
        message = await bot.send_photo(chat_id, FSInputFile(photo), caption=text, reply_markup=markup)
    else:
        message = await bot.send_message(chat_id, text, reply_markup=markup)
    return message.message_id


def invite_text(tour: Tour) -> str:
    dates = format_date_range(tour.start_date, tour.end_date)
    return (
        f"🎉 <b>Ваша заявка одобрена</b>\n\n"
        f"🧳 {escape(tour.title)}\n📅 {escape(dates)}\n\n"
        "Вступайте в группу участников: там общение и новости по поездке. "
        "Ссылка личная — после нажатия бот впустит вас автоматически."
    )


async def send_invite(bot: Bot, chat_id: int, application: Application, tour: Tour) -> str:
    """Создаёт личную ссылку «с одобрением» и присылает её автору заявки. Возвращает ссылку."""
    if not application.telegram_user_id:
        raise InviteError("У заявки нет Telegram ID — некому отправить приглашение.")
    invite = await bot.create_chat_invite_link(
        chat_id, name=f"Заявка №{application.id}"[:32], creates_join_request=True,
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👥 Вступить в группу",
                                                                         url=invite.invite_link)]])
    try:
        await bot.send_message(application.telegram_user_id, invite_text(tour), reply_markup=markup)
    except TelegramForbiddenError as exc:
        raise InviteError("Человек заблокировал бота — приглашение не доставлено.") from exc
    return invite.invite_link


async def send_rejection(bot: Bot, application: Application, tour: Tour) -> None:
    if not application.telegram_user_id:
        return
    text = (f"Организатор не смог подтвердить вашу заявку на тур «{escape(tour.title)}». "
            "Посмотрите другие поездки в каталоге.")
    try:
        await bot.send_message(application.telegram_user_id, text)
    except TelegramAPIError as exc:
        logger.warning("Rejection message for application %s failed: %s", application.id,
                       exc.__class__.__name__)


class InviteError(Exception):
    """Понятная владельцу причина, по которой приглашение не отправлено."""
