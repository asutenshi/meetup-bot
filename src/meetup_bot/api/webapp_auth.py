"""Валидация Telegram Web App ``initData`` (TZ §3.2).

Frontend кладёт подписанную строку `initData` в заголовок
``X-Telegram-Init-Data`` при каждом запросе к ``/api/*``. Здесь — разбор и
проверка этой строки и FastAPI-зависимости, переиспользуемые всеми ручками.

Проверка подписи (HMAC-SHA256, `secret_key = HMAC_SHA256("WebAppData", bot_token)`,
константное сравнение) делегирована `aiogram.utils.web_app`; сверх неё тут —
проверка возраста `auth_date` (защита от replay) и наличия поля `user`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from aiogram.utils.web_app import WebAppInitData, safe_parse_webapp_init_data
from fastapi import Depends, Header, HTTPException, Request, status

INIT_DATA_HEADER = "X-Telegram-Init-Data"

logger = logging.getLogger("meetup_bot.api")


class InitDataError(Exception):
    """`initData` не прошла валидацию.

    `reason` — короткий машиночитаемый код, он же уходит в `detail` ответа
    ``401`` (`invalid_signature` / `expired` / `no_user` / `missing`).
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def parse_init_data(raw: str, *, bot_token: str, max_age: timedelta) -> WebAppInitData:
    """Проверить подпись и срок годности `initData`, вернуть разобранные данные.

    Бросает `InitDataError` при любой проблеме — вызывающий сам решает, как её
    показать (в API это `401`).
    """
    if not raw:
        raise InitDataError("missing")

    try:
        data = safe_parse_webapp_init_data(bot_token, raw)
    except ValueError as exc:
        # Битая query-string, отсутствующий/неверный `hash`.
        raise InitDataError("invalid_signature") from exc

    auth_date = data.auth_date
    if auth_date.tzinfo is None:
        auth_date = auth_date.replace(tzinfo=UTC)
    if datetime.now(tz=UTC) - auth_date > max_age:
        raise InitDataError("expired")

    if data.user is None:
        # Технически подпись валидна, но без `user` идентифицировать некого
        # (например, Web App открыт не из чата, а как ссылка на канал).
        raise InitDataError("no_user")

    return data


def get_init_data(
    request: Request,
    init_data_header: Annotated[str | None, Header(alias=INIT_DATA_HEADER)] = None,
) -> WebAppInitData:
    """FastAPI-зависимость: разобранная и проверенная `initData` запроса.

    Отдаёт `401` с машиночитаемым `detail`, если заголовка нет или он не
    прошёл валидацию.
    """
    settings = request.app.state.settings
    try:
        return parse_init_data(
            init_data_header or "",
            bot_token=settings.bot_token,
            max_age=timedelta(seconds=settings.webapp_init_data_max_age),
        )
    except InitDataError as exc:
        # initData не прошла валидацию — обязательное к логированию событие
        # (TZ §6.2). `missing` (нет заголовка) частый и безобидный — его в INFO.
        level = logging.INFO if exc.reason == "missing" else logging.WARNING
        logger.log(
            level,
            "initData validation failed",
            extra={"reason": exc.reason, "path": request.url.path},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=exc.reason,
        ) from exc


def get_tg_user_id(init_data: Annotated[WebAppInitData, Depends(get_init_data)]) -> int:
    """FastAPI-зависимость: `tg_user_id` из проверенной `initData`."""
    user = init_data.user
    if user is None:  # pragma: no cover — гарантировано parse_init_data
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="no_user",
        )
    return user.id
