from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.methods import Response, TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import ErrorEvent, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger("meetup_bot.bot")


class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self._session_factory() as session:
            data["session"] = session
            return await handler(event, data)


class TelegramErrorLoggingMiddleware(BaseRequestMiddleware):
    """Централизованно логирует неуспешные вызовы Bot API (TZ §6.2).

    В частности `403 bot was blocked by the user` — сигнал, что человек
    заблокировал бота (пометку на `User`/`ProjectMembership` ставит задача 5.1).
    Исключение не гасится: обработку берут на себя вызывающие — рассылки в
    worker'е ловят `TelegramAPIError` по каждому получателю, обновление анонса
    глотает ошибку редактирования.
    """

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        try:
            return await make_request(bot, method)
        except TelegramRetryAfter as exc:
            logger.warning(
                "telegram api flood limit",
                extra={"api_method": type(method).__name__, "retry_after": exc.retry_after},
            )
            raise
        except TelegramAPIError as exc:
            logger.warning(
                "telegram api error",
                extra={
                    "api_method": type(method).__name__,
                    "error": type(exc).__name__,
                    "detail": str(exc),
                },
            )
            raise


async def log_unhandled_update_exception(event: ErrorEvent) -> bool:
    """Catch-all для необработанных исключений хендлеров (TZ §6.2).

    Логирует с трейсбеком и помечает апдейт обработанным — иначе исключение
    вылетает из `feed_update` в вебхук-эндпоинт (`app.py`), тот отвечает `500`,
    и Telegram повторяет доставку по кругу.
    """
    update = event.update
    logger.error(
        "unhandled update exception",
        exc_info=event.exception,
        extra={"update_id": update.update_id},
    )
    return True
