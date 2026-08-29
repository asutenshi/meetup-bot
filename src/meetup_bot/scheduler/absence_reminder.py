"""Джоба: личное напоминание участнику «давно не виделись» (TZ §3.4, п.2).

Второй шаг периодического прохода worker-процесса. В отличие от финализации явки
(шаг 1), шлёт людям сообщения, поэтому:

- рассылает только в проходе, попавшем на час `ProjectSettings.reminder_send_hour`
  по таймзоне проекта (по умолчанию 20:00) — чтобы уведомления не приходили ночью;
  проходы в остальные часы для этого проекта — no-op;
- троттлит не чаще одного напоминания в сутки на участника
  (`ProjectMembership.last_reminder_sent_at`).

Кандидаты — активные участники с `consecutive_missed_events <
missed_events_escalation_count` (по достижении порога участник переходит на
эскалацию организатору/админу, шаг 3 — `escalation.py`) и «тишиной» дольше
`reminder_days_threshold` дней (от `last_attended_at`, либо от `registered_at`,
если участник вообще ни разу не был отмечен).
"""

import logging
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from meetup_bot.db.enums import EventStatus, MembershipStatus
from meetup_bot.db.models import Event, Project, ProjectMembership, ProjectSettings
from meetup_bot.scheduler.timezones import DEFAULT_TZ, as_utc, resolve_project_tz

logger = logging.getLogger("meetup_bot.scheduler")

# Дефолты на случай отсутствующей строки `ProjectSettings` — те же, что
# `server_default` соответствующих полей.
_DEFAULT_SEND_HOUR = 20
_DEFAULT_DAYS_THRESHOLD = 14
_DEFAULT_ESCALATION_COUNT = 3

# Окно троттлинга: одно напоминание в сутки. Час рассылки один, а проходов в
# него несколько (интервал 15–30 мин) — окно чуть меньше суток схлопывает их в
# одно сообщение и при этом разрешает завтрашнюю рассылку в тот же час.
_THROTTLE_WINDOW = timedelta(hours=23)


def _absence_days(reference: datetime, now: datetime) -> int:
    return (now - as_utc(reference)).days


def _reminder_text(days: int, next_event: Event | None, tz_name: str) -> str:
    lines = [
        f"Привет! Мы не виделись с тобой уже больше {days} дней — заглядывай, "
        "тебя не хватает на встречах.",
    ]
    if next_event is not None:
        local_start = as_utc(next_event.starts_at).astimezone(resolve_project_tz(tz_name))
        when = local_start.strftime("%d.%m в %H:%M")
        title = next_event.title or "ближайшая встреча"
        lines.append(f"\n{title}: {when}, {next_event.location}.")
    return "\n".join(lines)


async def remind_absent_members(
    session: AsyncSession, bot: Bot | None = None, *, now: datetime | None = None
) -> None:
    """Рассылает личные напоминания «давно не виделись» (TZ §3.4, п.2).

    Транзакция шага держится открытой на время рассылки (сообщения идут по сети) —
    при десятках участников на проект это приемлемо; `last_reminder_sent_at`
    коммитится по завершении шага.
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

        days_threshold = (
            settings.reminder_days_threshold if settings is not None else _DEFAULT_DAYS_THRESHOLD
        )
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
                    ProjectMembership.consecutive_missed_events < escalation_count,
                )
                .options(selectinload(ProjectMembership.user))
            )
        ).all()
        if not memberships:
            continue

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

        for membership in memberships:
            reference = membership.last_attended_at or membership.registered_at
            days = _absence_days(reference, now)
            if days <= days_threshold:
                continue
            if (
                membership.last_reminder_sent_at is not None
                and now - as_utc(membership.last_reminder_sent_at) < _THROTTLE_WINDOW
            ):
                continue

            user = membership.user
            delivered = True
            if bot is not None:
                try:
                    await bot.send_message(
                        chat_id=user.tg_user_id,
                        text=_reminder_text(days, next_event, tz_name),
                    )
                except TelegramAPIError:
                    delivered = False
                    logger.warning(
                        "напоминание «давно не виделись»: не доставлено пользователю %d "
                        "(проект %d)",
                        user.tg_user_id,
                        project.id,
                        exc_info=True,
                    )
            # Даже при ошибке доставки помечаем попытку: троттлинг не даст
            # долбить заблокировавшего бота участника каждый проход.
            membership.last_reminder_sent_at = now
            if delivered:
                sent += 1

    logger.info("напоминание «давно не виделись»: разослано — %d", sent)
