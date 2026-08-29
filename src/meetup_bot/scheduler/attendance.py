"""Джоба финализации явки по списку RSVP (TZ §3.4, п.1).

Первый из трёх шагов периодического прохода worker-процесса. Полностью
работает по БД, без обращений к Telegram: в полночь следующего дня (в таймзоне
проекта) после эффективного окончания мероприятия фиксирует текущее состояние
`EventRSVP` как факт явки и обновляет счётчики посещаемости в
`ProjectMembership`.
"""

import logging
from datetime import UTC, datetime, time, timedelta

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from meetup_bot.db.enums import EventStatus, MembershipStatus, RSVPStatus
from meetup_bot.db.models import Event, ProjectMembership, ProjectSettings
from meetup_bot.scheduler.timezones import DEFAULT_TZ, resolve_project_tz

logger = logging.getLogger("meetup_bot.scheduler")


def _finalization_due_at(effective_end: datetime, tz_name: str) -> datetime:
    """Момент, начиная с которого мероприятие финализируется: полночь (в таймзоне
    проекта) дня, следующего за днём `effective_end` (`ends_at ?? starts_at`).

    Смещение на целые сутки — намеренный запас для организатора: до этого момента
    можно поправить чьи-то ошибочные самоотметки через корректировку `EventRSVP`
    (TZ §3.4, п.1; §4.3)."""
    tz = resolve_project_tz(tz_name)
    if effective_end.tzinfo is None:
        effective_end = effective_end.replace(tzinfo=UTC)
    local_end_date = effective_end.astimezone(tz).date()
    return datetime.combine(local_end_date + timedelta(days=1), time.min, tzinfo=tz)


async def finalize_attendance(
    session: AsyncSession, bot: Bot | None = None, *, now: datetime | None = None
) -> None:
    """Финализирует явку для всех «дозревших» мероприятий (TZ §3.4, п.1).

    `bot` — часть общего интерфейса шага прохода (`meetup_bot.scheduler._PASSES`);
    рассылающим шагам 4.3–4.4 он нужен, финализация явки в Telegram не ходит и
    аргумент игнорирует.

    Кандидаты: `status = planned` и `attendance_finalized_at IS NULL`. Фильтр по
    моменту финализации (полночь следующего дня в таймзоне проекта) считается в
    Python — таймзонная арифметика не переносится между SQLite и Postgres, а
    незакрытых мероприятий в проекте единицы.

    Для каждого дозревшего мероприятия: активные участники проекта с
    `EventRSVP.status = going` считаются присутствовавшими
    (`last_attended_at = now`, `consecutive_missed_events = 0`), все остальные
    активные участники (в т.ч. не ответившие на RSVP) — отсутствовавшими
    (`consecutive_missed_events += 1`). По завершении — `attendance_finalized_at =
    now`, повторно джоба мероприятие не берёт.
    """
    now = now or datetime.now(UTC)

    candidates = await session.scalars(
        select(Event)
        .where(
            Event.status == EventStatus.PLANNED,
            Event.attendance_finalized_at.is_(None),
        )
        .options(selectinload(Event.rsvps))
    )

    finalized = 0
    for event in candidates:
        settings = await session.get(ProjectSettings, event.project_id)
        tz_name = settings.timezone if settings is not None else DEFAULT_TZ
        if now < _finalization_due_at(event.ends_at or event.starts_at, tz_name):
            continue

        memberships = await session.scalars(
            select(ProjectMembership).where(
                ProjectMembership.project_id == event.project_id,
                ProjectMembership.status == MembershipStatus.ACTIVE,
            )
        )
        going_user_ids = {
            rsvp.user_id for rsvp in event.rsvps if rsvp.status == RSVPStatus.GOING
        }

        attended = missed = 0
        for membership in memberships:
            if membership.user_id in going_user_ids:
                membership.last_attended_at = now
                membership.consecutive_missed_events = 0
                attended += 1
            else:
                membership.consecutive_missed_events += 1
                missed += 1

        event.attendance_finalized_at = now
        finalized += 1
        logger.info(
            "финализация явки: событие %d (проект %d) — присутствовали %d, отсутствовали %d",
            event.id,
            event.project_id,
            attended,
            missed,
        )

    logger.info("финализация явки: обработано мероприятий — %d", finalized)
