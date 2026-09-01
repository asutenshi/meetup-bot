"""Права на мероприятие и подбор мероприятий для редактирования (TZ §4.3
«Редактирование/отмена», задача 2.7).

Право редактировать/отменять мероприятие и править чужой RSVP (задача 3.2):
организатор/со-организатор по `EventCoOrganizer`, либо, если таких строк нет, —
создатель мероприятия (`Event.created_by`) или админ проекта (`role=admin`).
Проверка должна выполняться и при показе списка `/edit_event`, и повторно на
бэкенде при сохранении.
"""

from __future__ import annotations

from datetime import UTC, datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.enums import EventStatus, MembershipRole, MembershipStatus, RSVPStatus
from meetup_bot.db.models import (
    Event,
    EventCoOrganizer,
    EventRSVP,
    ProjectMembership,
    User,
)


async def _co_organizer_ids(session: AsyncSession, event_id: int) -> set[int]:
    rows = await session.scalars(
        select(EventCoOrganizer.user_id).where(EventCoOrganizer.event_id == event_id)
    )
    return set(rows)


async def can_manage_event(
    session: AsyncSession, *, event: Event, user_id: int, is_admin: bool
) -> bool:
    """Есть ли у участника `user_id` право редактировать/отменять `event`.

    Со-организаторы заданы (`EventCoOrganizer` не пуст) → право строго у них
    (даже создатель, снявший себя из организаторов, теряет доступ). Строк нет →
    у создателя мероприятия или любого админа проекта (TZ §4.3)."""
    co_ids = await _co_organizer_ids(session, event.id)
    if co_ids:
        return user_id in co_ids
    return user_id == event.created_by or is_admin


async def list_manageable_events(
    session: AsyncSession, *, project_id: int, user_id: int, is_admin: bool
) -> list[Event]:
    """Запланированные, ещё не финализированные мероприятия проекта, которые
    участник `user_id` вправе редактировать — для списка `/edit_event`.
    Отсортированы по времени начала (ближайшие сверху)."""
    events = await session.scalars(
        select(Event)
        .where(
            Event.project_id == project_id,
            Event.status == EventStatus.PLANNED,
            Event.attendance_finalized_at.is_(None),
        )
        .order_by(Event.starts_at, Event.id)
    )
    result: list[Event] = []
    for event in events:
        if await can_manage_event(
            session, event=event, user_id=user_id, is_admin=is_admin
        ):
            result.append(event)
    return result


def _as_utc(moment: datetime) -> datetime:
    """Naive `datetime` из SQLite трактуем как UTC; aware — приводим к UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _effective_end(event: Event) -> datetime:
    return _as_utc(event.ends_at or event.starts_at)


async def list_events_for_rsvp_correction(
    session: AsyncSession,
    *,
    project_id: int,
    user_id: int,
    is_admin: bool,
    now: datetime | None = None,
) -> list[Event]:
    """Мероприятия проекта для экрана постфактум-корректировки RSVP (задача 3.1).

    В отличие от `list_manageable_events` — без ограничения по
    `attendance_finalized_at` (RSVP правится и после финализации, TZ §4.4 п.1) и
    по давности; отсеиваются только отменённые. Право — то же `can_manage_event`.
    Порядок: сначала ближайшие предстоящие (по возрастанию даты), затем недавно
    прошедшие (по убыванию) — корректируют чаще всего только что прошедшее."""
    now = _as_utc(now or datetime.now(UTC))
    rows = await session.scalars(
        select(Event).where(
            Event.project_id == project_id,
            Event.status != EventStatus.CANCELLED,
        )
    )
    manageable = [
        event
        for event in rows
        if await can_manage_event(
            session, event=event, user_id=user_id, is_admin=is_admin
        )
    ]
    upcoming = sorted(
        (e for e in manageable if _effective_end(e) >= now), key=_effective_end
    )
    past = sorted(
        (e for e in manageable if _effective_end(e) < now),
        key=_effective_end,
        reverse=True,
    )
    return [*upcoming, *past]


async def recompute_membership_attendance(
    session: AsyncSession, *, project_id: int, user_id: int
) -> None:
    """Пересчитывает `last_attended_at` / `consecutive_missed_events` одного
    участника заново по всем финализированным мероприятиям проекта — вызывается
    после постфактум-правки его RSVP на уже финализированном мероприятии
    (TZ §3.4 п.1 последний абзац, §4.4 п.2).

    «Точечно» = трогаем счётчики только этого участника, остальных не пересчитываем
    и `attendance_finalized_at` не откатываем. Считать простой дельтой ±1 нельзя:
    прежнее значение `last_attended_at` при правке `going → не-going` уже потеряно,
    — поэтому проходим хронологию (`COALESCE(ends_at, starts_at)`, `id`) заново: на
    мероприятии с финальным `EventRSVP.status = going` участник «присутствовал»
    (`last_attended_at = event.attendance_finalized_at`, счётчик пропусков в ноль),
    иначе «пропустил» (счётчик += 1). Мероприятия, финализированные до вступления
    участника в проект, пропускаем — джоба финализации их ему не засчитывала."""
    membership = await session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user_id,
        )
    )
    if membership is None:
        return

    events = list(
        await session.scalars(
            select(Event)
            .where(
                Event.project_id == project_id,
                Event.attendance_finalized_at.is_not(None),
            )
            .order_by(func.coalesce(Event.ends_at, Event.starts_at), Event.id)
        )
    )
    going_event_ids = set(
        await session.scalars(
            select(EventRSVP.event_id)
            .join(Event, Event.id == EventRSVP.event_id)
            .where(
                Event.project_id == project_id,
                EventRSVP.user_id == user_id,
                EventRSVP.status == RSVPStatus.GOING,
            )
        )
    )
    joined_at = (
        _as_utc(membership.registered_at)
        if membership.registered_at is not None
        else None
    )

    last_attended_at: datetime | None = None
    missed = 0
    for event in events:
        finalized_at = event.attendance_finalized_at
        assert finalized_at is not None  # гарантировано фильтром выше
        if joined_at is not None and _as_utc(finalized_at) < joined_at:
            continue
        if event.id in going_event_ids:
            last_attended_at = finalized_at
            missed = 0
        else:
            missed += 1

    membership.last_attended_at = last_attended_at
    membership.consecutive_missed_events = missed


async def is_latest_finalized_event(session: AsyncSession, event: Event) -> bool:
    """`event` — самое недавно финализированное мероприятие своего проекта?
    Пересчёт счётчиков после правки RSVP разрешён только для него (см.
    `recompute_membership_attendance`): для более ранних финализированных
    мероприятий понятие «подряд пропущенных» пришлось бы пересобирать всем
    затронутым участникам, что выходит за рамки задачи 3.2."""
    latest_id = await session.scalar(
        select(Event.id)
        .where(
            Event.project_id == event.project_id,
            Event.attendance_finalized_at.is_not(None),
        )
        .order_by(Event.attendance_finalized_at.desc(), Event.id.desc())
        .limit(1)
    )
    return latest_id == event.id


async def resolve_member_user_id(
    session: AsyncSession, *, project_id: int, tg_user_id: int
) -> int | None:
    """Внутренний `User.id` активного участника проекта по его `tg_user_id`
    (`None`, если не участник). Нужен командам `/edit_event` и `/cancel_event`,
    которые собирают мероприятия по всем проектам вызвавшего."""
    row = await session.scalar(
        select(User.id)
        .join(ProjectMembership, ProjectMembership.user_id == User.id)
        .where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.status == MembershipStatus.ACTIVE,
            User.tg_user_id == tg_user_id,
        )
    )
    return int(row) if row is not None else None


async def going_members(session: AsyncSession, event: Event) -> list[User]:
    """Активные участники проекта, подтвердившие участие (`EventRSVP.status =
    going`) — адресаты личных уведомлений об изменении/отмене мероприятия."""
    return list(
        await session.scalars(
            select(User)
            .join(EventRSVP, EventRSVP.user_id == User.id)
            .join(
                ProjectMembership,
                (ProjectMembership.user_id == User.id)
                & (ProjectMembership.project_id == event.project_id)
                & (ProjectMembership.status == MembershipStatus.ACTIVE),
            )
            .where(
                EventRSVP.event_id == event.id,
                EventRSVP.status == RSVPStatus.GOING,
            )
            .order_by(EventRSVP.responded_at, EventRSVP.id)
        )
    )


async def notify_going_members(
    bot: Bot,
    session: AsyncSession,
    event: Event,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> int:
    """Рассылает `text` в личку всем подтвердившим участие. Ошибку доставки
    конкретному человеку (бот заблокирован, чат не начат) глотаем — она не
    должна ронять сохранение изменений. Возвращает число доставленных."""
    delivered = 0
    for user in await going_members(session, event):
        try:
            await bot.send_message(
                chat_id=user.tg_user_id, text=text, reply_markup=reply_markup
            )
        except TelegramAPIError:
            continue
        delivered += 1
    return delivered


async def user_is_project_admin(
    session: AsyncSession, *, project_id: int, user_id: int
) -> bool:
    """`role in (owner, admin)` для активного членства по внутреннему `user_id`
    (в отличие от `services.projects.is_project_admin`, работающего по
    `tg_user_id`)."""
    membership = await session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user_id,
            ProjectMembership.status == MembershipStatus.ACTIVE,
            ProjectMembership.role.in_([MembershipRole.OWNER, MembershipRole.ADMIN]),
        )
    )
    return membership is not None
