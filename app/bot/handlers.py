"""Обработчики Telegram-бота: deep link /start <tour_code> и сбор демо-заявки."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    User,
)

from app.bot import texts
from app.config import Settings
from app.database import session_scope
from app.models import Application, Tour
from app.services import tours as tour_service
from app.services.applications import (
    ApplicationValidationError,
    create_application,
    normalize_comment,
    normalize_name,
)

logger = logging.getLogger(__name__)
router = Router(name="naomi_tours")

APPLY_PREFIX = "apply:"
SKIP_COMMENT = "comment:skip"
CONFIRM = "app:confirm"
CANCEL = "app:cancel"


class ApplicationForm(StatesGroup):
    name = State()
    comment = State()
    confirm = State()


# ---------- клавиатуры ----------

def apply_keyboard(tour: Tour) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📝 Оставить заявку", callback_data=f"{APPLY_PREFIX}{tour.id}")
    ]])


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
        return texts.tour_unavailable(lookup.tour, settings)
    return texts.tour_not_found(settings)


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
        await message.answer(texts.session_expired(settings), reply_markup=ReplyKeyboardRemove())
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
        await message.answer(_lookup_error_text(lookup, settings))
        return
    await message.answer(texts.tour_card(lookup.tour, settings), reply_markup=apply_keyboard(lookup.tour))


@router.message(CommandStart())
async def start_plain(message: Message, state: FSMContext, settings: Settings) -> None:
    await state.clear()
    await message.answer(texts.welcome(settings), reply_markup=ReplyKeyboardRemove())


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
    await callback.message.answer(texts.CANCELLED, reply_markup=ReplyKeyboardRemove())


# ---------- сбор заявки ----------

@router.callback_query(F.data.startswith(APPLY_PREFIX))
async def apply_start(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await callback.answer()
    raw_id = callback.data.removeprefix(APPLY_PREFIX)
    if not raw_id.isdigit():
        await callback.message.answer(texts.tour_not_found(settings))
        return
    lookup = _load_public_tour(int(raw_id))
    if lookup.status is not tour_service.LookupStatus.OK:
        await state.clear()
        await callback.message.answer(_lookup_error_text(lookup, settings))
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
    await message.answer("Спасибо!", reply_markup=ReplyKeyboardRemove())
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
    await state.update_data(comment="")
    await _show_summary(callback.message, state, callback.from_user.username, settings)


@router.callback_query(ApplicationForm.confirm, F.data == CONFIRM)
async def confirm_application(callback: CallbackQuery, state: FSMContext, bot: Bot,
                              settings: Settings) -> None:
    await callback.answer()
    data = await state.get_data()
    user = callback.from_user
    with session_scope() as session:
        tour = session.get(Tour, data.get("tour_id", 0))
        if tour is None or not tour.is_public(tour_service.current_date()):
            await state.clear()
            await callback.message.answer(texts.session_expired(settings))
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
    await callback.message.answer(texts.application_saved(application, organizer_notified=notified))


@router.callback_query(F.data.in_({CONFIRM, SKIP_COMMENT}))
async def stale_button(callback: CallbackQuery, settings: Settings) -> None:
    await callback.answer()
    await callback.message.answer(texts.session_expired(settings))


@router.message(StateFilter(ApplicationForm.name, ApplicationForm.comment))
async def non_text_in_form(message: Message) -> None:
    await message.answer(texts.TEXT_EXPECTED)


@router.message(ApplicationForm.confirm)
async def text_on_confirm(message: Message) -> None:
    await message.answer(texts.USE_BUTTONS)


@router.message()
async def fallback(message: Message, settings: Settings) -> None:
    await message.answer(texts.welcome(settings))
