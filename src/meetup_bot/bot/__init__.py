from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.bot.handlers import all_members, chat_member, setup_registration, start
from meetup_bot.bot.handlers.all_members import AllThrottleMiddleware
from meetup_bot.bot.middlewares import DbSessionMiddleware
from meetup_bot.config import Settings


def create_bot(settings: Settings) -> Bot:
    return Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def create_dispatcher(session_factory: async_sessionmaker[AsyncSession]) -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.update.outer_middleware(DbSessionMiddleware(session_factory))
    dispatcher.update.outer_middleware(AllThrottleMiddleware())
    dispatcher.include_router(chat_member.create_router())
    dispatcher.include_router(setup_registration.create_router())
    dispatcher.include_router(start.create_router())
    dispatcher.include_router(all_members.create_router())
    return dispatcher
