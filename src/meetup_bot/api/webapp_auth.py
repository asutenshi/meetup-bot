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

# Допуск на рассинхронизацию часов: `auth_date` в будущем в пределах этого
# окна считаем валидным (возрастом 0), дальше — `clock_skew`, а не `expired`.
CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)

logger = logging.getLogger("meetup_bot.api")


class InitDataError(Exception):
    """`initData` не прошла валидацию.

    `reason` — короткий машиночитаемый код, он же уходит в `detail` ответа
    ``401`` (`invalid_signature` / `expired` / `clock_skew` / `no_user` /
    `missing`).

    Для возрастных ошибок (`expired` / `clock_skew`) заполнены `age_seconds` и
    `max_age_seconds` — они уходят в лог-событие, чтобы по логам отличать
    зависшего пользователя от дрейфа часов сервера (TZ §6.2).
    """

    def __init__(
        self,
        reason: str,
        *,
        age_seconds: float | None = None,
        max_age_seconds: float | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.age_seconds = age_seconds
        self.max_age_seconds = max_age_seconds


def parse_init_data(
    raw: str,
    *,
    bot_token: str,
    max_age: timedelta,
    reject_stale: bool = True,
) -> WebAppInitData:
    """Проверить подпись `initData`, вернуть разобранные данные.

    Настоящая аутентификация — HMAC-подпись; `auth_date` лишь ограничивает окно
    replay. Telegram-клиенты (в первую очередь Desktop) кэшируют launch-параметры
    и не обновляют `auth_date` даже между полными перезапусками — у пользователя
    нет способа получить свежую `initData`. Поэтому просрочку по возрасту по
    умолчанию отклоняем (`reject_stale=True` — примитив строгий), но вызывающий
    (`get_init_data`) передаёт сюда политику из настроек: в проде проверка
    сделана необязательной (`reject_stale=False` → только WARNING в лог).

    Бросает `InitDataError` при проблеме — вызывающий решает, как её показать
    (в API это `401`).
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
    age = datetime.now(tz=UTC) - auth_date
    if age < -CLOCK_SKEW_TOLERANCE:
        # `auth_date` в будущем относительно часов сервера сверх допуска — это
        # не replay, а рассинхронизация времени (обычно на стороне сервера).
        # Отдаём отдельным кодом: и в логах виднее, и фронт не пугает
        # пользователя текстом «сессия устарела».
        raise InitDataError(
            "clock_skew",
            age_seconds=age.total_seconds(),
            max_age_seconds=max_age.total_seconds(),
        )
    if max_age > timedelta(0) and age > max_age:
        if reject_stale:
            raise InitDataError(
                "expired",
                age_seconds=age.total_seconds(),
                max_age_seconds=max_age.total_seconds(),
            )
        # Необязательный режим: подпись валидна, пускаем, но фиксируем возраст —
        # по логам видно, что организатор сидит на закэшированной клиентом
        # `initData` (TZ §6.2).
        logger.warning(
            "initData stale but accepted",
            extra={
                "age_seconds": round(age.total_seconds()),
                "max_age_seconds": round(max_age.total_seconds()),
            },
        )

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
            reject_stale=settings.webapp_init_data_reject_stale,
        )
    except InitDataError as exc:
        # initData не прошла валидацию — обязательное к логированию событие
        # (TZ §6.2). `missing` (нет заголовка) частый и безобидный — его в INFO.
        level = logging.INFO if exc.reason == "missing" else logging.WARNING
        extra: dict[str, object] = {"reason": exc.reason, "path": request.url.path}
        if exc.age_seconds is not None:
            extra["age_seconds"] = round(exc.age_seconds)
        if exc.max_age_seconds is not None:
            extra["max_age_seconds"] = round(exc.max_age_seconds)
        logger.log(level, "initData validation failed", extra=extra)
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
