"""Профиль Telegram-бота: имя, описания и команды.

Проверить текущий профиль (ничего не меняет):  python -m app.bot.profile
Применить профиль Naomi Tours:                  python -m app.bot.profile --apply

Username (@...) этим скриптом не меняется — это делается только через @BotFather.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from aiogram import Bot
from aiogram.types import BotCommand

from app.config import load_settings

BOT_NAME = "Naomi Tours"  # до 64 символов
BOT_SHORT_DESCRIPTION = (  # до 120 символов: «About» в профиле и превью ссылки на бота
    "Групповые поездки из Франкфурта и Майнца: Испания, Грузия, Франция. Заявки на туры."
)
BOT_DESCRIPTION = (  # до 512 символов: экран до нажатия «Start»
    "Здесь оставляют заявки на групповые поездки Naomi Tours "
    "с выездом из Франкфурта и Майнца.\n\n"
    "1. Выберите тур на сайте\n"
    "2. Нажмите «Оставить заявку» — бот откроется с этим туром\n"
    "3. Укажите имя\n\n"
    "Заявка не является бронированием: место подтверждает организатор."
)
BOT_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="cancel", description="Отменить заявку"),
]

assert len(BOT_NAME) <= 64 and len(BOT_SHORT_DESCRIPTION) <= 120 and len(BOT_DESCRIPTION) <= 512


async def read_profile(bot: Bot) -> dict:
    me = await bot.get_me()
    return {
        "name": me.first_name,
        "username": me.username,
        "short_description": (await bot.get_my_short_description()).short_description,
        "description": (await bot.get_my_description()).description,
        "commands": [(c.command, c.description) for c in await bot.get_my_commands()],
    }


def profile_matches(profile: dict) -> bool:
    return (
        profile["name"] == BOT_NAME
        and profile["short_description"] == BOT_SHORT_DESCRIPTION
        and profile["description"] == BOT_DESCRIPTION
        and profile["commands"] == [(c.command, c.description) for c in BOT_COMMANDS]
    )


async def apply_profile(bot: Bot) -> None:
    await bot.set_my_name(name=BOT_NAME)
    await bot.set_my_short_description(short_description=BOT_SHORT_DESCRIPTION)
    await bot.set_my_description(description=BOT_DESCRIPTION)
    await bot.set_my_commands(BOT_COMMANDS)


def _print_profile(profile: dict) -> None:
    print(f"Имя:              {profile['name']}  (@{profile['username']})")
    print(f"Короткое описание: {profile['short_description'] or '—'}")
    print(f"Описание:          {profile['description'] or '—'}")
    print(f"Команды:           {profile['commands'] or '—'}")
    print("Профиль соответствует Naomi Tours." if profile_matches(profile)
          else "Профиль НЕ соответствует Naomi Tours (запустите с --apply).")


async def run(apply: bool) -> None:
    settings = load_settings()
    if not settings.bot_token:
        sys.exit("BOT_TOKEN не задан в .env.")
    bot = Bot(settings.bot_token)
    try:
        if apply:
            await apply_profile(bot)
            print("Профиль применён.\n")
        _print_profile(await read_profile(bot))
    finally:
        await bot.session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Профиль Telegram-бота Naomi Tours")
    parser.add_argument("--apply", action="store_true", help="записать имя, описания и команды")
    asyncio.run(run(parser.parse_args().apply))


if __name__ == "__main__":
    main()
