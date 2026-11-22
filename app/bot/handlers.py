"""Обработчики Telegram-бота: deep link /start <tour_code> и сбор демо-заявки."""
from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, F, Router
from sqlalchemy import select
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    ChatJoinRequest,
    ChatMemberUpdated,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    User,
)

from app.bot import texts
from app.config import STATIC_DIR, Settings
from app.database import session_scope
from app.models import Application, Tour
from app.models.application import STATUS_APPROVED
from app.services import app_settings, telegram_group
from app.services import tours as tour_service
from app.services.applications import (
    ApplicationValidationError,
    create_application,
    normalize_comment,
    normalize_name,
)

logger = logging.getLogger(__name__)
router = Router(name="naomi_tours")
# Бот — администратор демо-группы и видит все сообщения в ней: отвечаем только в личных чатах.
router.message.filter(F.chat.type == "private")

APPLY_PREFIX = "apply:"
SKIP_COMMENT = "comment:skip"
CONFIRM = "app:confirm"
CANCEL = "app:cancel"
CAPTION_LIMIT = 1024  # ограничение Telegram на подпись к фото


class ApplicationForm(StatesGroup):
    name = State()
    comment = State()
    confirm = State()


# ---------- клавиатуры ----------

def _site_button(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def catalog_keyboard(settings: Settings) -> InlineKeyboardMarkup | None:
    """Кнопка на каталог — только если сайт открывается не только на этом компьютере."""
    if not settings.site_is_public:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[_site_button("🌍 Открыть каталог", settings.catalog_url)]])


def tour_keyboard(tour: Tour, settings: Settings) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="📝 Оставить заявку", callback_data=f"{APPLY_PREFIX}{tour.id}")]]
    if settings.site_is_public:
        rows.append([_site_button("🌐 Подробнее на сайте", settings.tour_url(tour.tour_code))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def name_keyboard(user: User | None) -> ReplyKeyboardMarkup | ReplyKeyboardRemove:
    full_name = (user.full_name or "").strip() if user else ""
    if not full_name:
        return ReplyKeyboardRemove()
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=full_name[:64])]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def comment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Пропустить", callback_data=SKIP_COMMENT),
        InlineKeyboardButton(text="Отменить", callback_data=CANCEL),
    ]])


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Отправить", callback_data=CONFIRM),
        InlineKeyboardButton(text="❌ Отменить", callback_data=CANCEL),
    ]])


# ---------- вспомогательные функции ----------

def _load_public_tour(tour_id: int) -> tour_service.TourLookup:
    with session_scope() as session:
        tour = session.get(Tour, tour_id)
        if tour is None:
            return tour_service.TourLookup(tour_service.LookupStatus.NOT_FOUND)
        if not tour.is_public(tour_service.current_date()):
            return tour_service.TourLookup(tour_service.LookupStatus.UNAVAILABLE, tour)
        return tour_service.TourLookup(tour_service.LookupStatus.OK, tour)


def _lookup_error_text(lookup: tour_service.TourLookup, settings: Settings) -> str:
    if lookup.status is tour_service.LookupStatus.UNAVAILABLE and lookup.tour is not None:
        return texts.tour_unavailable(lookup.tour, settings.site_is_public)
    return texts.tour_not_found(settings.site_is_public)


def tour_photo_path(tour: Tour):
    """Локальное фото тура для карточки в боте; None, если фото нет."""
    if not tour.image:
        return None
    path = STATIC_DIR / tour.image
    return path if path.is_file() else None


async def _drop_buttons(message: Message) -> None:
    """Убирает кнопки с уже отвеченного сообщения, чтобы их нельзя было нажать повторно."""
    try:
        await message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError as exc:
        logger.debug("Could not remove buttons: %s", exc.__class__.__name__)


async def notify_admin(bot: Bot, settings: Settings, application: Application, tour: Tour) -> bool:
    """Отправляет уведомление в ADMIN_CHAT_ID, только если он явно задан."""
    if settings.admin_chat_id is None:
        return False
    try:
        await bot.send_message(settings.admin_chat_id, texts.admin_notification(application, tour))
    except TelegramAPIError as exc:
        logger.warning("Admin notification for application %s failed: %s",
                       application.id, exc.__class__.__name__)
        return False
    return True


async def _show_summary(message: Message, state: FSMContext, username: str | None,
                        settings: Settings) -> None:
    data = await state.get_data()
    lookup = _load_public_tour(data["tour_id"])
    if lookup.status is not tour_service.LookupStatus.OK:
        await state.clear()
        await message.answer(texts.session_expired(settings.site_is_public),
                             reply_markup=catalog_keyboard(settings))
        return
    await state.set_state(ApplicationForm.confirm)
    await message.answer(
        texts.summary(lookup.tour, data["name"], data.get("comment", ""), username),
        reply_markup=confirm_keyboard(),
    )


# ---------- /start ----------

@router.message(CommandStart(deep_link=True))
async def start_with_code(message: Message, command: CommandObject, state: FSMContext,
                          settings: Settings) -> None:
    await state.clear()
    with session_scope() as session:
        lookup = tour_service.find_public_tour(session, command.args or "", tour_service.current_date())
    if lookup.status is not tour_service.LookupStatus.OK:
        await message.answer(_lookup_error_text(lookup, settings), reply_markup=catalog_keyboard(settings))
        return
    tour = lookup.tour
    card = texts.tour_card(tour)
    keyboard = tour_keyboard(tour, settings)
    photo = tour_photo_path(tour)
    if photo is not None and len(card) <= CAPTION_LIMIT:
        await message.answer_photo(FSInputFile(photo), caption=card, reply_markup=keyboard)
    else:
        await message.answer(card, reply_markup=keyboard)


@router.message(CommandStart())
async def start_plain(message: Message, state: FSMContext, settings: Settings) -> None:
    await state.clear()
    await message.answer(texts.welcome(settings.site_is_public),
                         reply_markup=catalog_keyboard(settings) or ReplyKeyboardRemove())


# ---------- отмена ----------

@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext) -> None:
    had_state = await state.get_state() is not None
    await state.clear()
    await message.answer(texts.CANCELLED if had_state else texts.NOTHING_TO_CANCEL,
                         reply_markup=ReplyKeyboardRemove())


@router.callback_query(F.data == CANCEL)
async def cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await _drop_buttons(callback.message)
    await callback.message.answer(texts.CANCELLED, reply_markup=ReplyKeyboardRemove())


# ---------- сбор заявки ----------

@router.callback_query(F.data.startswith(APPLY_PREFIX))
async def apply_start(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await callback.answer()
    raw_id = callback.data.removeprefix(APPLY_PREFIX)
    if not raw_id.isdigit():
        await callback.message.answer(texts.tour_not_found(settings.site_is_public),
                                      reply_markup=catalog_keyboard(settings))
        return
    lookup = _load_public_tour(int(raw_id))
    if lookup.status is not tour_service.LookupStatus.OK:
        await state.clear()
        await callback.message.answer(_lookup_error_text(lookup, settings),
                                      reply_markup=catalog_keyboard(settings))
        return
    await state.clear()
    await state.update_data(tour_id=lookup.tour.id)
    await state.set_state(ApplicationForm.name)
    await callback.message.answer(texts.ask_name(), reply_markup=name_keyboard(callback.from_user))


@router.message(ApplicationForm.name, F.text)
async def process_name(message: Message, state: FSMContext) -> None:
    try:
        name = normalize_name(message.text)
    except ApplicationValidationError as exc:
        await message.answer(f"{exc} Попробуйте ещё раз или /cancel.")
        return
    await state.update_data(name=name)
    await state.set_state(ApplicationForm.comment)
    await message.answer(texts.name_accepted(name), reply_markup=ReplyKeyboardRemove())
    await message.answer(texts.ask_comment(), reply_markup=comment_keyboard())


@router.message(ApplicationForm.comment, F.text)
async def process_comment(message: Message, state: FSMContext, settings: Settings) -> None:
    try:
        comment = normalize_comment(message.text)
    except ApplicationValidationError as exc:
        await message.answer(f"{exc} Сократите текст или нажмите «Пропустить».")
        return
    await state.update_data(comment=comment)
    username = message.from_user.username if message.from_user else None
    await _show_summary(message, state, username, settings)


@router.callback_query(ApplicationForm.comment, F.data == SKIP_COMMENT)
async def skip_comment(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await callback.answer()
    await _drop_buttons(callback.message)
    await state.update_data(comment="")
    await _show_summary(callback.message, state, callback.from_user.username, settings)


@router.callback_query(ApplicationForm.confirm, F.data == CONFIRM)
async def confirm_application(callback: CallbackQuery, state: FSMContext, bot: Bot,
                              settings: Settings) -> None:
    await callback.answer()
    await _drop_buttons(callback.message)
    data = await state.get_data()
    user = callback.from_user
    with session_scope() as session:
        tour = session.get(Tour, data.get("tour_id", 0))
        if tour is None or not tour.is_public(tour_service.current_date()):
            await state.clear()
            await callback.message.answer(texts.session_expired(settings.site_is_public),
                                          reply_markup=catalog_keyboard(settings))
            return
        application = create_application(
            session,
            tour,
            name=data["name"],
            comment=data.get("comment", ""),
            telegram_user_id=user.id if user else None,
            telegram_username=user.username if user else None,
        )
    await state.clear()
    logger.info("Demo application %s saved for tour %s", application.id, tour.tour_code)
    notified = await notify_admin(bot, settings, application, tour)
    await callback.message.answer(
        texts.application_saved(application, tour, organizer_notified=notified),
        reply_markup=catalog_keyboard(settings),
    )


@router.callback_query(F.data.in_({CONFIRM, SKIP_COMMENT}))
async def stale_button(callback: CallbackQuery, settings: Settings) -> None:
    await callback.answer()
    await _drop_buttons(callback.message)
    await callback.message.answer(texts.session_expired(settings.site_is_public),
                                  reply_markup=catalog_keyboard(settings))


# ---------- демо-группа ----------

GROUP_TYPES = {"group", "supergroup"}
ACTIVE_STATUSES = {"administrator", "member"}


@router.my_chat_member()
async def bot_membership_changed(event: ChatMemberUpdated) -> None:
    """Бота добавили в группу — она появится в админке для подтверждения; удалили — забываем её."""
    if event.chat.type not in GROUP_TYPES:
        return
    with session_scope() as session:
        if event.new_chat_member.status in ACTIVE_STATUSES:
            connected = app_settings.connected_group(session)
            if connected is None or connected.chat_id != event.chat.id:
                app_settings.remember_pending_group(session, event.chat.id, event.chat.title or "Группа",
                                                    bool(event.chat.is_forum))
                logger.info("Bot added to group %s, waiting for admin confirmation", event.chat.id)
        else:
            app_settings.forget_group(session, event.chat.id)
            logger.info("Bot removed from group %s", event.chat.id)


def approved_tours_for(user_id: int) -> list[Tour]:
    with session_scope() as session:
        return list(session.scalars(
            select(Tour).join(Application, Application.tour_id == Tour.id)
            .where(Application.telegram_user_id == user_id, Application.status == STATUS_APPROVED)
        ))


@router.chat_join_request()
async def join_request(request: ChatJoinRequest, bot: Bot) -> None:
    """В группу впускаем только людей с одобренной заявкой."""
    with session_scope() as session:
        group = app_settings.connected_group(session)
    if group is None or request.chat.id != group.chat_id:
        return
    tours = approved_tours_for(request.from_user.id)
    if not tours:
        await request.decline()
        logger.info("Join request declined: no approved application")
        return
    await request.approve()
    lines = ["👋 Добро пожаловать в группу участников!"]
    for tour in tours:
        link = telegram_group.topic_link(group.chat_id, tour.forum_topic_id)
        if link:
            lines.append(f"Тема вашего тура «{escape(tour.title)}»: {link}")
    try:
        await bot.send_message(request.from_user.id, "\n".join(lines))
    except TelegramAPIError as exc:
        logger.warning("Welcome message failed: %s", exc.__class__.__name__)


@router.message(StateFilter(ApplicationForm.name, ApplicationForm.comment))
async def non_text_in_form(message: Message) -> None:
    await message.answer(texts.TEXT_EXPECTED)


@router.message(ApplicationForm.confirm)
async def text_on_confirm(message: Message) -> None:
    await message.answer(texts.USE_BUTTONS)


@router.message()
async def fallback(message: Message, settings: Settings) -> None:
    await message.answer(texts.welcome(settings.site_is_public), reply_markup=catalog_keyboard(settings))
