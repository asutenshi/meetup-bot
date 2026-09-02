"""Структурированное логирование в stdout (TZ §6.2).

Одна точка настройки для обоих режимов (`bot+api` и `worker`): JSON-строка на
строку вывода, без внешних библиотек — при нашем масштабе достаточно
`logging.StreamHandler(stdout)` + свой `Formatter`. Ротацию делает Docker
(`max-size`/`max-file`, см. `docker-compose.yml`), поэтому файловых хендлеров
здесь нет.

Дополнительные поля события передаются через штатный `extra=` у логгера
(`logger.warning(..., extra={"chat_id": 42})`) и попадают в JSON верхним уровнем.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Атрибуты `LogRecord`, которые формируются самим `logging`; всё, что вне этого
# набора, считаем переданным через `extra=` и кладём в JSON.
_RESERVED_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {"message", "asctime", "taskName"}

# Шумные сторонние логгеры, которым на INFO не место (иначе каждый апдейт/запрос
# даёт по несколько строк). Оставляем WARNING — ошибки и предупреждения видны.
_NOISY_LOGGERS = ("aiogram.event", "httpx", "httpcore", "uvicorn.access")


class JsonFormatter(logging.Formatter):
    """Форматирует запись как одну JSON-строку.

    Обязательные поля: `ts` (ISO-8601, UTC), `level`, `logger`, `message`.
    `exc` добавляется для записей с исключением, всё из `extra=` — как есть.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(*, level: str | int = "INFO") -> None:
    """Настроить корневой логгер на JSON-вывод в stdout.

    Идемпотентна: повторный вызов заменяет хендлеры, не плодит их (важно для
    тестов и для `uvicorn`, который трогает конфиг логирования при старте).
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    for existing in root.handlers[:]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    # uvicorn по умолчанию вешает свои хендлеры на эти логгеры — снимаем, чтобы
    # его строки шли через наш JSON-хендлер корня, а не дублировались обычным
    # текстом.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
