"""Джоба: эскалация организатору/админу (TZ §3.4, п.3).

Третий шаг периодического прохода worker-процесса. Как только участник набирает
`consecutive_missed_events >= missed_events_escalation_count`, личные напоминания
ему прекращаются (шаг 2 — `absence_reminder.py` — отбирает только тех, у кого
счётчик строго меньше порога), и вместо этого один раз в период уведомляются
люди, которые могут написать лично:

- со-организаторы ближайшего запланированного мероприятия проекта;
- если ближайшего мероприятия нет либо у него нет со-организаторов —
  админы проекта (`role in (owner, admin)`).

Со-организаторы прошедших мероприятий получателями не становятся: если у проекта
нет ни одного будущего мероприятия, эскалация уходит админам.

Как и личное напоминание, эскалация уходит только в проходе, попавшем на час
`ProjectSettings.reminder_send_hour` по таймзоне проекта. Троттлинг —
`ProjectMembership.last_escalation_sent_at`, не чаще одной эскалации в неделю на
пару участник—проект.
"""

import logging
from datetime import UTC, datetime, timedelta
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from meetup_bot.db.enums import EventStatus, MembershipRole, MembershipStatus
from meetup_bot.db.models import (
    Event,
    EventCoOrganizer,
    Project,
    ProjectMembership,
    ProjectSettings,
    User,
)
from meetup_bot.scheduler.timezones import DEFAULT_TZ, as_utc, resolve_project_tz

logger = logging.getLogger("meetup_bot.scheduler")

# Дефолты на случай отсутствующей строки `ProjectSettings` — те же, что
# `server_default` соответствующих полей.
_DEFAULT_SEND_HOUR = 20
_DEFAULT_ESCALATION_COUNT = 3

_ADMIN_ROLES = (MembershipRole.OWNER, MembershipRole.ADMIN)

# Троттлинг: одна эскалация в неделю на пару участник—проект. Окно чуть меньше
# 7 суток — по той же причине, что и в `absence_reminder`: час рассылки один, а
# проходов в него несколько, и завтра/через неделю в тот же час рассылка снова
# разрешена.
_THROTTLE_WINDOW = timedelta(days=6, hours=23)


def _missed_events_word(count: int) -> str:
    """Склонение слова «встреча» для «пропустил подряд N встреч»."""
    if count % 10 == 1 and count % 100 != 11:
        return "встречу"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "встречи"
    return "встреч"


def _escalation_text(user: User, missed: int) -> str:
    if user.username:
        mention = f"@{escape(user.username)}"
    else:
        mention = f'<a href="tg://user?id={user.tg_user_id}">{escape(user.first_name)}</a>'
    return (
        f"{mention} пропустил(а) подряд {missed} {_missed_events_word(missed)} — "
        "возможно, стоит написать лично."
    )


async def _resolve_recipients(
    session: AsyncSession, project: Project, now: datetime
) -> list[User]:
    """Кому уходит эскалация по проекту: со-организаторы ближайшего запланированного
    мероприятия, а если такого мероприятия нет либо у него нет со-организаторов —
    админы проекта."""
    next_event = await session.scalar(
        select(Event)
        .where(
            Event.project_id == project.id,
            Event.status == EventStatus.PLANNED,
            Event.starts_at > now,
        )
        .order_by(Event.starts_at)
        .limit(1)
    )

    if next_event is not None:
        co_organizers = (
            await session.scalars(
                select(EventCoOrganizer)
                .where(EventCoOrganizer.event_id == next_event.id)
                .options(selectinload(EventCoOrganizer.user))
            )
        ).all()
        if co_organizers:
            return [co.user for co in co_organizers]

    admins = (
        await session.scalars(
            select(ProjectMembership)
            .where(
                ProjectMembership.project_id == project.id,
                ProjectMembership.status == MembershipStatus.ACTIVE,
                ProjectMembership.role.in_(_ADMIN_ROLES),
            )
            .options(selectinload(ProjectMembership.user))
        )
    ).all()
    return [m.user for m in admins]


async def escalate_missed_events(
    session: AsyncSession, bot: Bot | None = None, *, now: datetime | None = None
) -> None:
    """Уведомляет организаторов/админов о набравших порог пропусков (TZ §3.4, п.3).

    Транзакция шага держится открытой на время рассылки — сообщений немного
    (эскалации редки), `last_escalation_sent_at` коммитится по завершении шага.
    """
    now = now or datetime.now(UTC)

    projects = await session.scalars(select(Project).where(Project.is_active.is_(True)))
    sent = 0
    for project in projects:
        settings = await session.get(ProjectSettings, project.id)
        tz_name = settings.timezone if settings is not None else DEFAULT_TZ
        send_hour = settings.reminder_send_hour if settings is not None else _DEFAULT_SEND_HOUR
        if now.astimezone(resolve_project_tz(tz_name)).hour != send_hour:
            continue

        escalation_count = (
            settings.missed_events_escalation_count
            if settings is not None
            else _DEFAULT_ESCALATION_COUNT
        )

        memberships = (
            await session.scalars(
                select(ProjectMembership)
                .where(
                    ProjectMembership.project_id == project.id,
                    ProjectMembership.status == MembershipStatus.ACTIVE,
                    ProjectMembership.consecutive_missed_events >= escalation_count,
                )
                .options(selectinload(ProjectMembership.user))
            )
        ).all()
        pending = [
            m
            for m in memberships
            if m.last_escalation_sent_at is None
            or now - as_utc(m.last_escalation_sent_at) >= _THROTTLE_WINDOW
        ]
        if not pending:
            continue

        recipients = await _resolve_recipients(session, project, now)

        for membership in pending:
            absent = membership.user
            # Про самого прогульщика ему же не пишем — даже если он админ и попал
            # в список получателей как таковой.
            targets = [r for r in recipients if r.tg_user_id != absent.tg_user_id]
            if not targets:
                logger.warning(
                    "эскалация: проект %d, участник %d — некому отправить "
                    "(нет со-организаторов и других админов)",
                    project.id,
                    absent.tg_user_id,
                )
                continue

            text = _escalation_text(absent, membership.consecutive_missed_events)
            for recipient in targets:
                if bot is None:
                    continue
                try:
                    await bot.send_message(chat_id=recipient.tg_user_id, text=text)
                    sent += 1
                except TelegramAPIError:
                    logger.warning(
                        "эскалация: не доставлено получателю %d (проект %d, участник %d)",
                        recipient.tg_user_id,
                        project.id,
                        absent.tg_user_id,
                        exc_info=True,
                    )
            # Троттлинг ставится и когда bot is None (worker без рассылки), и когда
            # все доставки упали — чтобы не долбить получателей каждый проход.
            membership.last_escalation_sent_at = now

    logger.info("эскалация: отправлено уведомлений — %d", sent)
