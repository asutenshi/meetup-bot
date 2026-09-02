import logging

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from aiogram.types import ErrorEvent, Update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.bot import create_dispatcher
from meetup_bot.bot.middlewares import (
    TelegramErrorLoggingMiddleware,
    log_unhandled_update_exception,
)

BOT_TOKEN = "123:abc"


def test_create_dispatcher_registers_error_handler(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dispatcher = create_dispatcher(session_factory)

    callbacks = [handler.callback for handler in dispatcher.errors.handlers]
    assert log_unhandled_update_exception in callbacks


async def test_telegram_error_middleware_logs_and_reraises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    method = SendMessage(chat_id=1, text="x")
    blocked = TelegramForbiddenError(
        method=method, message="Forbidden: bot was blocked by the user"
    )

    async def make_request(bot: Bot, m: object) -> object:
        raise blocked

    middleware = TelegramErrorLoggingMiddleware()
    caplog.set_level(logging.WARNING, logger="meetup_bot.bot")

    with pytest.raises(TelegramForbiddenError):
        await middleware(make_request, Bot(token=BOT_TOKEN), method)

    (record,) = caplog.records
    assert record.message == "telegram api error"
    assert record.api_method == "SendMessage"
    assert record.error == "TelegramForbiddenError"
    assert "blocked by the user" in record.detail


async def test_telegram_error_middleware_logs_flood_limit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    method = SendMessage(chat_id=1, text="x")

    async def make_request(bot: Bot, m: object) -> object:
        raise TelegramRetryAfter(method=method, message="Too Many Requests", retry_after=7)

    caplog.set_level(logging.WARNING, logger="meetup_bot.bot")

    with pytest.raises(TelegramRetryAfter):
        await TelegramErrorLoggingMiddleware()(make_request, Bot(token=BOT_TOKEN), method)

    (record,) = caplog.records
    assert record.message == "telegram api flood limit"
    assert record.retry_after == 7


async def test_telegram_error_middleware_passes_success_through() -> None:
    method = SendMessage(chat_id=1, text="x")
    sentinel = object()

    async def make_request(bot: Bot, m: object) -> object:
        return sentinel

    result = await TelegramErrorLoggingMiddleware()(
        make_request, Bot(token=BOT_TOKEN), method
    )

    assert result is sentinel


async def test_log_unhandled_update_exception_logs_with_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    event = ErrorEvent(
        update=Update(update_id=555),
        exception=RuntimeError("handler blew up"),
    )
    caplog.set_level(logging.ERROR, logger="meetup_bot.bot")

    handled = await log_unhandled_update_exception(event)

    assert handled is True
    (record,) = caplog.records
    assert record.message == "unhandled update exception"
    assert record.update_id == 555
    assert record.exc_info is not None
    assert "handler blew up" in caplog.text
