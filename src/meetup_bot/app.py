from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import FastAPI, Request

from meetup_bot.api import router as api_router
from meetup_bot.bot import create_bot, create_dispatcher
from meetup_bot.bot.commands import set_bot_commands
from meetup_bot.config import Settings, get_settings
from meetup_bot.db.session import create_engine, create_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.session_factory = create_session_factory(engine)
        app.state.bot = create_bot(settings)
        app.state.dispatcher = create_dispatcher(app.state.session_factory)
        # Подсказки команд по `/` — до начала обработки апдейтов (TZ §3.6).
        await set_bot_commands(app.state.bot)
        try:
            yield
        finally:
            await app.state.bot.session.close()
            await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(api_router)

    # Путь включает BOT_TOKEN как секрет (см. scripts/set_webhook.py) — так
    # посторонние запросы на публичный адрес не путаются с апдейтами Telegram.
    @app.post(f"/webhook/{settings.bot_token}")
    async def webhook(request: Request) -> dict[str, str]:
        bot: Bot = request.app.state.bot
        dispatcher: Dispatcher = request.app.state.dispatcher
        update = Update.model_validate(await request.json())
        await dispatcher.feed_update(bot=bot, update=update)
        return {"status": "ok"}

    return app
