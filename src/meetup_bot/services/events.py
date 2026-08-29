"""Права на мероприятие и подбор мероприятий для редактирования (TZ §4.3
«Редактирование/отмена», задача 2.7).

Право редактировать/отменять мероприятие и править чужой RSVP (задача 3.2):
организатор/со-организатор по `EventCoOrganizer`, либо, если таких строк нет, —
создатель мероприятия (`Event.created_by`) или админ проекта (`role=admin`).
Проверка должна выполняться и при показе списка `/edit_event`, и повторно на
бэкенде при сохранении.
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
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
    bot: Bot, session: AsyncSession, event: Event, *, text: str
) -> int:
    """Рассылает `text` в личку всем подтвердившим участие. Ошибку доставки
    конкретному человеку (бот заблокирован, чат не начат) глотаем — она не
    должна ронять сохранение изменений. Возвращает число доставленных."""
    delivered = 0
    for user in await going_members(session, event):
        try:
            await bot.send_message(chat_id=user.tg_user_id, text=text)
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
