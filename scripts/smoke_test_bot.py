"""Разовая ручная проверка связи с Telegram Bot API.

Не часть приложения — запускается вручную для проверки сетевого доступа
из окружения (например, из LXC-контейнера с Tailscale Funnel) до начала
разработки. Не привязан к CMD в Dockerfile и не входит в roadmap TASKS.md.

Использование:
    uv run python scripts/smoke_test_bot.py

Требует переменные окружения (см. .env):
    BOT_TOKEN      — токен бота от @BotFather
    TEST_CHAT_ID   — chat_id получателя тестового сообщения
                      (узнать: написать боту /start, посмотреть в
                      https://api.telegram.org/bot<token>/getUpdates)
"""

import asyncio
import os
import sys

from aiogram import Bot
from dotenv import load_dotenv


async def main() -> None:
    load_dotenv()

    token = os.environ.get("BOT_TOKEN")
    chat_id = os.environ.get("TEST_CHAT_ID")

    if not token:
        sys.exit("BOT_TOKEN не задан (проверьте .env)")
    if not chat_id:
        sys.exit("TEST_CHAT_ID не задан (проверьте .env)")

    bot = Bot(token=token)
    try:
        me = await bot.get_me()
        print(f"OK: авторизован как @{me.username} (id={me.id})")

        await bot.send_message(
            chat_id=chat_id,
            text="✅ Тестовое сообщение: бот запущен и достучался до Telegram API.",
        )
        print(f"OK: сообщение отправлено в chat_id={chat_id}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
