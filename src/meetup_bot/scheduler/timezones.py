"""Общий резолвер таймзоны проекта для шагов периодического прохода (TZ §3.4).

`ProjectSettings.timezone` — свободная строка, до появления админского UI
(задача 4.5) правится только напрямую в БД, поэтому в ней теоретически может
оказаться мусор. Джобы не должны на этом падать — неизвестное значение
заменяется на дефолт с предупреждением в лог.
"""

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger("meetup_bot.scheduler")

# Совпадает с `ProjectSettings.timezone.server_default`.
DEFAULT_TZ = "Europe/Moscow"


def resolve_project_tz(tz_name: str) -> ZoneInfo:
    """`ZoneInfo` по имени из `ProjectSettings.timezone`; при нераспознанном
    значении — `DEFAULT_TZ` с предупреждением."""
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning(
            "проход напоминаний: неизвестная таймзона %r, беру %s", tz_name, DEFAULT_TZ
        )
        return ZoneInfo(DEFAULT_TZ)


def as_utc(moment: datetime) -> datetime:
    """Naive `datetime` трактуется как UTC (так его отдаёт SQLite для
    `DateTime(timezone=True)`); aware — приводится к UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)
