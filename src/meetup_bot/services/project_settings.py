"""Реестр редактируемых параметров `ProjectSettings` и их валидация.

Общий код для команды `/settings` (`bot/handlers/settings.py`, быстрый путь из
группового чата) и Web App-экрана настроек проекта (`api/project_settings.py`,
задача 4.5). Диапазоны чисел и разбор таймзоны IANA описаны здесь один раз —
хендлер и API только вызывают `parse_setting` / `apply_settings`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from html import escape
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from meetup_bot.db.models import ProjectSettings

SettingKind = Literal["int", "timezone"]


class SettingValueError(ValueError):
    """Значение параметра не прошло валидацию. `str(exc)` — готовый текст для
    пользователя (команда печатает его как есть, API кладёт в `message`); `code`
    — машиночитаемый код (`unknown_key` / `out_of_range` / `bad_timezone`)."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SettingSpec:
    """Один редактируемый параметр `ProjectSettings`. `attr` совпадает с именем
    поля модели и с ключом, который вводит пользователь / шлёт форма."""

    attr: str
    describe: str
    kind: SettingKind
    parse: Callable[[str], int | str]
    minimum: int | None = None
    maximum: int | None = None


def _int_in_range(attr: str, low: int, high: int) -> Callable[[str], int]:
    message = f"{attr}: нужно целое число от {low} до {high}."

    def parse(raw: str) -> int:
        try:
            value = int(raw)
        except ValueError:
            raise SettingValueError(message, code="out_of_range") from None
        if not low <= value <= high:
            raise SettingValueError(message, code="out_of_range")
        return value

    return parse


def _parse_timezone(raw: str) -> str:
    try:
        ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError):
        raise SettingValueError(
            f"Не распознал таймзону «{escape(raw)}». Укажите название из базы IANA, "
            "например Europe/Moscow или Asia/Novosibirsk.",
            code="bad_timezone",
        ) from None
    return raw


EDITABLE_SETTINGS: tuple[SettingSpec, ...] = (
    SettingSpec(
        attr="reminder_days_threshold",
        describe="через сколько дней «не виделись» слать личное напоминание участнику",
        kind="int",
        parse=_int_in_range("reminder_days_threshold", 1, 365),
        minimum=1,
        maximum=365,
    ),
    SettingSpec(
        attr="missed_events_escalation_count",
        describe=(
            "после скольких пропущенных подряд мероприятий переключаться "
            "с личных напоминаний на эскалацию организатору/админу"
        ),
        kind="int",
        parse=_int_in_range("missed_events_escalation_count", 1, 100),
        minimum=1,
        maximum=100,
    ),
    SettingSpec(
        attr="reminder_send_hour",
        describe=(
            "час (0–23) локального времени проекта, в который worker "
            "рассылает напоминания и эскалации"
        ),
        kind="int",
        parse=_int_in_range("reminder_send_hour", 0, 23),
        minimum=0,
        maximum=23,
    ),
    SettingSpec(
        attr="all_command_throttle_seconds",
        describe=(
            "минимальный интервал между вызовами /all в одном чате, сек "
            "(0 — без троттлинга)"
        ),
        kind="int",
        parse=_int_in_range("all_command_throttle_seconds", 0, 3600),
        minimum=0,
        maximum=3600,
    ),
    SettingSpec(
        attr="timezone",
        describe="таймзона проекта (IANA) для расчёта времени напоминаний",
        kind="timezone",
        parse=_parse_timezone,
    ),
)

SETTINGS_BY_ATTR: dict[str, SettingSpec] = {spec.attr: spec for spec in EDITABLE_SETTINGS}


def parse_setting(attr: str, raw: str) -> int | str:
    """Разобрать и проверить значение параметра `attr`. Бросает
    `SettingValueError`: `unknown_key` — нет такого параметра; `out_of_range` —
    не число или число вне диапазона; `bad_timezone` — не распознали зону."""
    spec = SETTINGS_BY_ATTR.get(attr)
    if spec is None:
        raise SettingValueError(
            f"Неизвестный параметр «{escape(attr)}».", code="unknown_key"
        )
    return spec.parse(raw.strip())


def apply_settings(
    settings: ProjectSettings, values: Mapping[str, int | str]
) -> list[tuple[str, object, object]]:
    """Проставить уже проверенные `values` в строку `ProjectSettings`. Возвращает
    `(attr, old, new)` только для реально изменившихся полей (для ответа/логов)."""
    changes: list[tuple[str, object, object]] = []
    for attr, new_value in values.items():
        old_value = getattr(settings, attr)
        if old_value != new_value:
            setattr(settings, attr, new_value)
            changes.append((attr, old_value, new_value))
    return changes
