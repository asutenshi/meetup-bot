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
from meetup_bot.services.event_announcement import (
    build_event_cancelled_notification,
    refresh_event_announcement,
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


async def list_project_events(
    session: AsyncSession, *, project_id: int
) -> list[tuple[Event, int]]:
    """Мероприятия проекта (кроме отменённых) вместе со счётчиком подтвердивших
    участие — для списка на домашнем экране-хабе Web App (`GET /api/projects/
    {payload}/events`, задача 2.9.1). Отсортированы по времени начала."""
    going = (
        select(EventRSVP.event_id, func.count().label("n"))
        .where(EventRSVP.status == RSVPStatus.GOING)
        .group_by(EventRSVP.event_id)
        .subquery()
    )
    rows = await session.execute(
        select(Event, func.coalesce(going.c.n, 0))
        .outerjoin(going, going.c.event_id == Event.id)
        .where(
            Event.project_id == project_id,
            Event.status != EventStatus.CANCELLED,
        )
        .order_by(Event.starts_at, Event.id)
    )
    return [(row[0], int(row[1])) for row in rows]


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


async def cancel_event(
    bot: Bot,
    session: AsyncSession,
    event: Event,
    *,
    timezone: str,
) -> tuple[bool, int]:
    """Отмена мероприятия: `status = cancelled`, перерисовка анонса (RSVP-кнопки
    и списки участников убираются, снизу — пометка «отменено») и личные
    уведомления подтвердившим участие. Общий сервис для команды `/cancel_event`
    (задача 2.8) и экрана мероприятия в Web App (задача 2.9.3); права и то, что
    мероприятие ещё можно отменить, проверяет вызывающий.

    Неправимый анонс (сообщение удалили, бот потерял права, публикации не было)
    отмене не мешает — она уже применена в БД, о неудаче сообщаем флагом.
    Возвращает `(announcement_ok, notified)`. `commit` делает сам.
    """
    event.status = EventStatus.CANCELLED
    await session.flush()
    try:
        announcement_ok = await refresh_event_announcement(bot, session, event)
    except TelegramAPIError:
        announcement_ok = False
    await session.commit()

    notified = await notify_going_members(
        bot,
        session,
        event,
        text=build_event_cancelled_notification(event, timezone=timezone),
    )
    return announcement_ok, notified


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
