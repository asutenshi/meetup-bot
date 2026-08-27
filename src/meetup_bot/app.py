from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

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
    # Доступ к конфигу из зависимостей (валидация Web App initData, TZ §3.2).
    app.state.settings = settings
    app.include_router(api_router)
    _mount_webapp(app, settings)

    # Путь включает BOT_TOKEN как секрет (см. scripts/set_webhook.py) — так
    # посторонние запросы на публичный адрес не путаются с апдейтами Telegram.
    # `include_in_schema=False` — чтобы токен не утёк в OpenAPI-схему (её дамп
    # идёт в TS-типы фронтенда, см. scripts/dump_openapi.py).
    @app.post(f"/webhook/{settings.bot_token}", include_in_schema=False)
    async def webhook(request: Request) -> dict[str, str]:
        bot: Bot = request.app.state.bot
        dispatcher: Dispatcher = request.app.state.dispatcher
        update = Update.model_validate(await request.json())
        await dispatcher.feed_update(bot=bot, update=update)
        return {"status": "ok"}

    return app


def _mount_webapp(app: FastAPI, settings: Settings) -> None:
    """Раздача собранного Telegram Mini App (Vite → webapp/dist) под /app.

    `html=True` отдаёт index.html на запрос каталога `/app/`. Пока сборки нет
    (dev без `npm run build`, CI без node) — просто не монтируем, бэкенд и
    вебхук работают как обычно.
    """
    dist = Path(settings.webapp_dist_dir)
    if not dist.is_dir():
        return
    app.mount("/app", StaticFiles(directory=dist, html=True), name="webapp")
