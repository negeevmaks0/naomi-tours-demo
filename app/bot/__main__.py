"""Запуск Telegram-бота (long polling): python -m app.bot"""
from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers import router
from app.bot.profile import BOT_NAME
from app.config import load_settings
from app.database import init_engine
from app.services.seed import init_db

logger = logging.getLogger("app.bot")


def build_dispatcher(settings) -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage(), settings=settings)
    dispatcher.include_router(router)
    return dispatcher


async def run() -> None:
    settings = load_settings()
    if not settings.bot_token:
        sys.exit("BOT_TOKEN не задан. Укажите токен от @BotFather в файле .env (см. .env.example).")

    engine = init_engine(settings.database_url)
    init_db(engine)

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me = await bot.get_me()
    if settings.bot_username and settings.bot_username.lower() != (me.username or "").lower():
        logger.warning("BOT_USERNAME (%s) does not match the token's bot (@%s): site links will be wrong",
                       settings.bot_username, me.username)
    if me.first_name != BOT_NAME:
        logger.warning("Bot profile is not set up (name: %s). Run: python -m app.bot.profile --apply",
                       me.first_name)
    if not settings.site_is_public:
        logger.warning("SITE_BASE_URL is a local address: bot messages will not include site links. "
                       "Set a public URL to show the demo on a phone (see README).")
    logger.info("Bot @%s started; admin notifications: %s",
                me.username, "on" if settings.admin_chat_id is not None else "off")
    try:
        await build_dispatcher(settings).start_polling(bot)
    finally:
        await bot.session.close()
        engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
