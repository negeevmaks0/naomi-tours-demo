"""Проверка сценариев бота без обращения к Telegram: хендлеры вызываются с фейковыми объектами."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select

from app.bot import handlers
from app.models import Application, Tour

USER = SimpleNamespace(id=555, username="test_user", full_name="Тест Тестов")


def run(coro):
    return asyncio.run(coro)


def make_state() -> FSMContext:
    return FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=USER.id, user_id=USER.id))


def make_message(text: str = "") -> SimpleNamespace:
    """Фейковое сообщение: все ответы (текст и фото) копятся в .sent как (текст, клавиатура, фото)."""
    msg = SimpleNamespace(text=text, from_user=USER, sent=[], edit_reply_markup=AsyncMock())

    async def answer(text, reply_markup=None, **_):
        msg.sent.append((text, reply_markup, None))

    async def answer_photo(photo, caption=None, reply_markup=None, **_):
        msg.sent.append((caption, reply_markup, photo))

    msg.answer = AsyncMock(side_effect=answer)
    msg.answer_photo = AsyncMock(side_effect=answer_photo)
    return msg


def make_callback(data: str) -> SimpleNamespace:
    return SimpleNamespace(data=data, from_user=USER, message=make_message(), answer=AsyncMock())


def last_text(message) -> str:
    return message.sent[-1][0]


def last_markup(message):
    return message.sent[-1][1]


def button_urls(markup) -> list[str]:
    rows = getattr(markup, "inline_keyboard", None) or []
    return [button.url for row in rows for button in row if button.url]


def start(args: str | None, settings, state=None):
    message = make_message(f"/start {args or ''}".strip())
    state = state or make_state()
    command = CommandObject(prefix="/", command="start", args=args)
    if args:
        run(handlers.start_with_code(message, command, state, settings))
    else:
        run(handlers.start_plain(message, state, settings))
    return message


def tour_id(db, code: str) -> int:
    return db.scalar(select(Tour.id).where(Tour.tour_code == code))


def test_start_without_argument_points_to_catalog(db, settings):
    message = start(None, settings)
    assert "Naomi Tours" in last_text(message)
    assert button_urls(last_markup(message)) == ["http://testserver/tours"]


def test_start_with_valid_code_shows_tour(db, settings):
    message = start("georgia_2027_03", settings)
    text = last_text(message)
    assert "Грузия — авиатур" in text
    assert "20–27 марта 2027" in text
    keyboard = last_markup(message)
    assert keyboard.inline_keyboard[0][0].callback_data == f"apply:{tour_id(db, 'georgia_2027_03')}"
    assert button_urls(keyboard) == ["http://testserver/tours/georgia_2027_03"]
    assert message.sent[-1][2] is None  # у Грузии нет фото — карточка текстом


def test_tour_with_photo_is_sent_as_photo_card(db, settings):
    message = start("andalusia_2027_03", settings)
    caption, keyboard, photo = message.sent[-1]
    assert photo is not None and str(photo.path).endswith("andalusia.jpg")
    assert "условные" in caption and len(caption) <= handlers.CAPTION_LIMIT
    assert keyboard.inline_keyboard[0][0].callback_data.startswith("apply:")


def test_start_with_unknown_code(db, settings):
    message = start("no_such_tour", settings)
    assert "Не нашли тур" in last_text(message)
    assert button_urls(last_markup(message)) == ["http://testserver/tours"]


def test_start_with_finished_tour(db, settings):
    text = last_text(start("burgundy_2026_11", settings))
    assert "уже начался или завершился" in text


def _fill_application(db, settings, code: str, bot, comment: str | None = "Нас двое"):
    state = make_state()
    run(handlers.apply_start(make_callback(f"apply:{tour_id(db, code)}"), state, settings))
    run(handlers.process_name(make_message("  Анна   Тест "), state))
    if comment is None:
        summary_msg = make_callback(handlers.SKIP_COMMENT)
        run(handlers.skip_comment(summary_msg, state, settings))
        summary_text = last_text(summary_msg.message)
    else:
        summary_msg = make_message(comment)
        run(handlers.process_comment(summary_msg, state, settings))
        summary_text = last_text(summary_msg)
    confirm = make_callback(handlers.CONFIRM)
    run(handlers.confirm_application(confirm, state, bot, settings))
    return state, summary_text, confirm


def test_full_application_flow_saves_with_correct_tour(db, settings):
    bot = SimpleNamespace(send_message=AsyncMock())
    state, summary_text, confirm = _fill_application(db, settings, "lloret_2027_06", bot)

    assert "Проверьте заявку" in summary_text
    assert "Анна Тест" in summary_text and "не является бронированием" in summary_text

    application = db.scalar(select(Application))
    assert application.tour_id == tour_id(db, "lloret_2027_06")
    assert application.name == "Анна Тест"
    assert application.comment == "Нас двое"
    assert application.telegram_user_id == USER.id
    assert application.telegram_username == USER.username
    saved_text = last_text(confirm.message)
    assert f"Заявка №{application.id} сохранена</b>" in saved_text
    confirm.message.edit_reply_markup.assert_awaited_once()  # кнопки сводки убраны
    assert "организатор" not in saved_text  # ADMIN_CHAT_ID не задан — ничего не обещаем
    assert "не является бронированием" in saved_text
    assert run(state.get_state()) is None
    bot.send_message.assert_not_called()


def test_skip_comment_and_admin_notification(db, settings):
    bot = SimpleNamespace(send_message=AsyncMock())
    admin_settings = replace(settings, admin_chat_id=-100123)
    _, _, confirm = _fill_application(db, admin_settings, "georgia_2027_03", bot, comment=None)
    assert "сохранена и отправлена организатору" in last_text(confirm.message)

    application = db.scalar(select(Application))
    assert application.comment == ""
    assert application.tour_id == tour_id(db, "georgia_2027_03")
    bot.send_message.assert_awaited_once()
    chat_id, text = bot.send_message.call_args.args
    assert chat_id == -100123
    assert "georgia_2027_03" in text


@pytest.mark.parametrize("bad_name", ["А", "12345", "x" * 101])
def test_invalid_name_is_rejected(db, settings, bad_name):
    state = make_state()
    run(handlers.apply_start(make_callback(f"apply:{tour_id(db, 'georgia_2027_03')}"), state, settings))
    message = make_message(bad_name)
    run(handlers.process_name(message, state))
    assert run(state.get_state()) == handlers.ApplicationForm.name.state
    assert "Попробуйте ещё раз" in last_text(message)


def test_apply_for_finished_tour_is_refused(db, settings):
    state = make_state()
    callback = make_callback(f"apply:{tour_id(db, 'burgundy_2026_11')}")
    run(handlers.apply_start(callback, state, settings))
    assert run(state.get_state()) is None
    assert "уже начался или завершился" in last_text(callback.message)


def test_cancel_clears_state(db, settings):
    state = make_state()
    run(handlers.apply_start(make_callback(f"apply:{tour_id(db, 'georgia_2027_03')}"), state, settings))
    message = make_message("/cancel")
    run(handlers.cancel_command(message, state))
    assert run(state.get_state()) is None
    assert "отменена" in last_text(message)
    assert db.scalar(select(Application)) is None


def test_failed_admin_notification_keeps_application_and_honest_text(db, settings):
    from aiogram.exceptions import TelegramNetworkError
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=TelegramNetworkError(method=None, message="down")))
    admin_settings = replace(settings, admin_chat_id=-100123)
    _, _, confirm = _fill_application(db, admin_settings, "georgia_2027_03", bot)
    assert db.scalar(select(Application)) is not None
    text = last_text(confirm.message)
    assert "сохранена</b>" in text and "отправлена организатору" not in text


def test_stale_confirm_button_message(db, settings):
    callback = make_callback(handlers.CONFIRM)
    run(handlers.stale_button(callback, settings))
    assert last_text(callback.message).startswith("Эта заявка уже не активна.")
    assert button_urls(last_markup(callback.message)) == ["http://testserver/tours"]


@pytest.mark.parametrize("base_url", ["http://127.0.0.1:8000", "http://localhost:8000", "http://0.0.0.0:8000"])
def test_local_site_url_is_never_sent_to_user(db, settings, base_url):
    local = replace(settings, site_base_url=base_url)
    sent = [start(None, local), start("georgia_2027_03", local), start("no_such_tour", local),
            start("burgundy_2026_11", local)]
    callback = make_callback(handlers.CONFIRM)
    run(handlers.stale_button(callback, local))
    sent.append(callback.message)
    for message in sent:
        text, markup = last_text(message), last_markup(message)
        assert "127.0.0.1" not in text and "localhost" not in text and "0.0.0.0" not in text
        assert button_urls(markup) == []


def test_public_site_url_used_in_all_links(db, settings):
    public = replace(settings, site_base_url="https://example.github.io/naomi-tours-demo/")
    site = "https://example.github.io/naomi-tours-demo"
    assert button_urls(last_markup(start(None, public))) == [f"{site}/tours"]
    assert button_urls(last_markup(start("georgia_2027_03", public))) == [f"{site}/tours/georgia_2027_03"]
    assert button_urls(last_markup(start("no_such_tour", public))) == [f"{site}/tours"]
