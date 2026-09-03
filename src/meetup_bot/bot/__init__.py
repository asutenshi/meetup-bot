from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.bot.handlers import (
    admin_commands,
    all_members,
    attendance,
    cancel_event,
    chat_member,
    chat_migration,
    edit_event,
    new_event,
    rsvp,
    set_topic,
    settings,
    setup_registration,
    start,
)
from meetup_bot.bot.handlers.all_members import AllThrottleMiddleware
from meetup_bot.bot.middlewares import (
    DbSessionMiddleware,
    TelegramErrorLoggingMiddleware,
    log_unhandled_update_exception,
)
from meetup_bot.config import Settings

# Наши вызовы Bot API короткие (send/edit/answer), long-polling не используем
# (вебхук). Дефолтные 60 с на запрос — это чистый простой при севшей сети до
# Telegram, за который под анонсом успевает протухнуть callback-запрос. 20 с
# хватает с запасом; на флуд-контроль это не влияет — его aiogram отдаёт
# отдельным `TelegramRetryAfter`, а не держит соединение.
_BOT_API_REQUEST_TIMEOUT_S = 20.0


def create_bot(settings: Settings) -> Bot:
    bot = Bot(
        token=settings.bot_token,
        session=AiohttpSession(timeout=_BOT_API_REQUEST_TIMEOUT_S),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    # Логирование неуспешных вызовов Bot API одним местом (TZ §6.2).
    bot.session.middleware(TelegramErrorLoggingMiddleware())
    return bot


def create_dispatcher(
    session_factory: async_sessionmaker[AsyncSession], app_settings: Settings | None = None
) -> Dispatcher:
    dispatcher = Dispatcher()
    # Конфиг доступен хендлерам как workflow-данные (аргумент `settings`).
    # `/new_event` строит по нему `web_app`-URL Mini App (TZ §3.8).
    dispatcher["settings"] = app_settings
    dispatcher.update.outer_middleware(DbSessionMiddleware(session_factory))
    dispatcher.update.outer_middleware(AllThrottleMiddleware())
    dispatcher.errors.register(log_unhandled_update_exception)
    dispatcher.include_router(chat_member.create_router())
    dispatcher.include_router(chat_migration.create_router())
    dispatcher.include_router(setup_registration.create_router())
    dispatcher.include_router(start.create_router())
    dispatcher.include_router(all_members.create_router())
    dispatcher.include_router(set_topic.create_router())
    dispatcher.include_router(settings.create_router())
    dispatcher.include_router(admin_commands.create_router())
    dispatcher.include_router(new_event.create_router())
    dispatcher.include_router(edit_event.create_router())
    dispatcher.include_router(cancel_event.create_router())
    dispatcher.include_router(attendance.create_router())
    dispatcher.include_router(rsvp.create_router())
    return dispatcher
