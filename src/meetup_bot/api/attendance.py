"""Экран постфактум-корректировки RSVP (Web App) — задачи 3.1 / 3.2.

Организатор/со-организатор (либо создатель/админ, если организатора нет) открывает
через `/attendance` экран со списком участников проекта и их текущим RSVP по
мероприятию и правит чужой статус в один тап. Каждое изменение — тот же
`EventRSVP` upsert, что и при самоотметке (`bot/handlers/rsvp.py`), но с
`updated_by` = id корректирующего (TZ §4.4 «Постфактум-корректировка RSVP»).

Правку RSVP финализация явки не блокирует (в отличие от самоотметки кнопкой):
- до финализации — правка просто меняет состояние и обновляет анонс;
- после финализации — дополнительно пересчитывает счётчики посещаемости
  скорректированного участника (`services.events.recompute_membership_attendance`),
  но только если это последнее финализированное мероприятие проекта
  (`is_latest_finalized_event`).
"""

from __future__ import annotations

from typing import Annotated, Literal

from aiogram import Bot
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.api.context import ProjectContext, get_bot, require_project_context
from meetup_bot.db.enums import EventStatus, MembershipRole, MembershipStatus, RSVPStatus
from meetup_bot.db.models import (
    Event,
    EventRSVP,
    ProjectMembership,
    ProjectSettings,
    User,
)
from meetup_bot.db.session import get_session
from meetup_bot.services.event_announcement import (
    DEFAULT_TIMEZONE,
    format_short_datetime,
    refresh_event_announcement,
)
from meetup_bot.services.events import (
    can_manage_event,
    is_latest_finalized_event,
    recompute_membership_attendance,
)

router = APIRouter(prefix="/api", tags=["attendance"])

RsvpStatusLiteral = Literal["going", "not_going"]

_STATUS_TO_ENUM: dict[str, RSVPStatus] = {
    "going": RSVPStatus.GOING,
    "not_going": RSVPStatus.NOT_GOING,
}
_ENUM_TO_STATUS: dict[RSVPStatus, RsvpStatusLiteral] = {
    RSVPStatus.GOING: "going",
    RSVPStatus.NOT_GOING: "not_going",
}


class AttendanceParticipant(BaseModel):
    user_id: int
    name: str
    # `null` — участник не ответил на RSVP (строки `EventRSVP` нет).
    status: RsvpStatusLiteral | None


class AttendanceContext(BaseModel):
    """Контекст экрана корректировки: подпись проекта/мероприятия и участники."""

    project_name: str
    event_label: str
    finalized: bool
    # Пересчёт счётчиков пропусков после правки возможен только для последнего
    # финализированного мероприятия проекта; для более ранних экран работает,
    # но счётчики не трогает (см. services.events.is_latest_finalized_event).
    counters_locked: bool
    participants: list[AttendanceParticipant]


class SetAttendanceRequest(BaseModel):
    user_id: int
    # `null` — сбросить отметку в «не ответил» (удалить строку `EventRSVP`).
    status: RsvpStatusLiteral | None


class SetAttendanceResponse(BaseModel):
    user_id: int
    status: RsvpStatusLiteral | None
    announcement_refreshed: bool
    counters_recomputed: bool


def _display_name(user: User) -> str:
    if user.last_name:
        return f"{user.first_name} {user.last_name}"
    return user.first_name


async def _active_members(
    session: AsyncSession, *, project_id: int
) -> list[User]:
    result = await session.scalars(
        select(User)
        .join(ProjectMembership, ProjectMembership.user_id == User.id)
        .where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.status == MembershipStatus.ACTIVE,
        )
        .order_by(User.first_name, User.id)
    )
    return list(result)


async def _load_correctable_event(
    session: AsyncSession, ctx: ProjectContext, event_id: int
) -> Event:
    """Мероприятие проекта из контекста, чей RSVP текущий пользователь вправе
    править. `404 event_not_found` — чужой/несуществующий id, `409
    event_cancelled` — отменено, `403 not_an_organizer` — нет прав. Уже
    финализированные мероприятия здесь допустимы (правку RSVP это не блокирует)."""
    event = await session.get(Event, event_id)
    if event is None or event.project_id != ctx.project.id:
        raise HTTPException(status_code=404, detail="event_not_found")
    if event.status == EventStatus.CANCELLED:
        raise HTTPException(status_code=409, detail="event_cancelled")

    is_admin = ctx.membership.role in (MembershipRole.OWNER, MembershipRole.ADMIN)
    if not await can_manage_event(
        session, event=event, user_id=ctx.user.id, is_admin=is_admin
    ):
        raise HTTPException(status_code=403, detail="not_an_organizer")
    return event


async def _event_label(session: AsyncSession, event: Event) -> str:
    settings = await session.get(ProjectSettings, event.project_id)
    timezone = settings.timezone if settings is not None else DEFAULT_TIMEZONE
    head = event.title or event.location
    return f"{format_short_datetime(event.starts_at, timezone)} · {head}"


@router.get("/events/{event_id}/attendance")
async def attendance_context(
    event_id: int,
    ctx: Annotated[ProjectContext, Depends(require_project_context)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AttendanceContext:
    event = await _load_correctable_event(session, ctx, event_id)
    members = await _active_members(session, project_id=ctx.project.id)
    rsvp_by_user = {
        row.user_id: row.status
        for row in await session.scalars(
            select(EventRSVP).where(EventRSVP.event_id == event.id)
        )
    }
    finalized = event.attendance_finalized_at is not None
    counters_locked = finalized and not await is_latest_finalized_event(session, event)
    return AttendanceContext(
        project_name=ctx.project.name,
        event_label=await _event_label(session, event),
        finalized=finalized,
        counters_locked=counters_locked,
        participants=[
            AttendanceParticipant(
                user_id=user.id,
                name=_display_name(user),
                status=(
                    _ENUM_TO_STATUS[rsvp_by_user[user.id]]
                    if user.id in rsvp_by_user
                    else None
                ),
            )
            for user in members
        ],
    )


@router.post("/events/{event_id}/attendance")
async def set_attendance(
    event_id: int,
    payload: SetAttendanceRequest,
    ctx: Annotated[ProjectContext, Depends(require_project_context)],
    session: Annotated[AsyncSession, Depends(get_session)],
    bot: Annotated[Bot, Depends(get_bot)],
) -> SetAttendanceResponse:
    event = await _load_correctable_event(session, ctx, event_id)

    target_membership = await session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == ctx.project.id,
            ProjectMembership.user_id == payload.user_id,
            ProjectMembership.status == MembershipStatus.ACTIVE,
        )
    )
    if target_membership is None:
        raise HTTPException(status_code=422, detail="not_a_member")

    rsvp = await session.scalar(
        select(EventRSVP).where(
            EventRSVP.event_id == event.id,
            EventRSVP.user_id == payload.user_id,
        )
    )
    target_enum = _STATUS_TO_ENUM[payload.status] if payload.status is not None else None

    if target_enum is None:
        changed = rsvp is not None
        if rsvp is not None:
            await session.delete(rsvp)
    elif rsvp is None:
        changed = True
        session.add(
            EventRSVP(
                event_id=event.id,
                user_id=payload.user_id,
                status=target_enum,
                updated_by=ctx.user.id,
            )
        )
    else:
        changed = rsvp.status != target_enum
        if changed:
            rsvp.status = target_enum
            rsvp.updated_by = ctx.user.id

    announcement_refreshed = False
    counters_recomputed = False
    if changed:
        await session.flush()
        announcement_refreshed = await refresh_event_announcement(bot, session, event)
        if event.attendance_finalized_at is not None and await is_latest_finalized_event(
            session, event
        ):
            await recompute_membership_attendance(
                session, project_id=ctx.project.id, user_id=payload.user_id
            )
            counters_recomputed = True
    await session.commit()

    return SetAttendanceResponse(
        user_id=payload.user_id,
        status=payload.status,
        announcement_refreshed=announcement_refreshed,
        counters_recomputed=counters_recomputed,
    )
