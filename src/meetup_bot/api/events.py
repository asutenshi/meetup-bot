"""`POST /api/events` — создание мероприятия из формы Web App (TZ §3.5, §4.3).

Форма Mini App (`webapp/`) шлёт сюда поля из TZ §4.3 п. 2, бэкенд создаёт
`Event` + строки `EventCoOrganizer` (ноль или больше) и от имени бота публикует
анонс в топик категории `events`. `GET /api/events/context` отдаёт форме всё,
что ей нужно для отрисовки: название проекта и список участников для выбора
со-организаторов.
"""

from __future__ import annotations

import datetime
import decimal
from typing import Annotated, Literal

from aiogram import Bot
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.api.context import ProjectContext, get_bot, require_project_context
from meetup_bot.db.enums import EventStatus, MembershipRole, MembershipStatus, RSVPStatus
from meetup_bot.db.models import Event, EventCoOrganizer, ProjectMembership, ProjectSettings, User
from meetup_bot.db.session import get_session
from meetup_bot.services.event_announcement import (
    DEFAULT_TIMEZONE,
    EventSnapshot,
    announcement_deep_link,
    build_event_update_keyboard,
    build_event_update_notification,
    load_announcement_participants,
    publish_event_announcement,
    refresh_event_announcement,
)
from meetup_bot.services.events import (
    can_manage_event,
    cancel_event,
    notify_going_members,
)
from meetup_bot.services.rsvp import (
    RsvpError,
    refresh_announcement_after_rsvp,
    rsvp_summary,
    set_rsvp,
)

router = APIRouter(prefix="/api", tags=["events"])


class EventFormMember(BaseModel):
    user_id: int
    name: str
    is_self: bool


class EventFormContext(BaseModel):
    """Контекст для отрисовки формы создания мероприятия."""

    project_name: str
    members: list[EventFormMember]


class CreateEventRequest(BaseModel):
    starts_at: datetime.datetime
    ends_at: datetime.datetime | None = None
    location: str = Field(min_length=1, max_length=255)
    # `description` — краткая афиша, идёт в анонс группы: лимит короткий, чтобы
    # само описание не переполнило сообщение Telegram (TZ §2.6, §4.3, §6.4).
    # Развёрнутый текст — в `details` (только экран мероприятия в Web App).
    description: str = Field(min_length=1, max_length=600)
    details: str | None = Field(default=None, max_length=4000)
    budget_per_person: decimal.Decimal | None = Field(default=None, ge=0, decimal_places=2)
    seats_limit: int | None = Field(default=None, ge=1)
    co_organizer_user_ids: list[int] = Field(default_factory=list)

    @field_validator("location", "description")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped

    @field_validator("details")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def _ends_after_starts(self) -> CreateEventRequest:
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class UpdateEventRequest(CreateEventRequest):
    """Тело `PUT /api/events/{id}` — те же поля, что и при создании (форма одна,
    предзаполненная, TZ §4.3)."""


class CreateEventResponse(BaseModel):
    event_id: int
    announcement_message_id: int | None


class EventFormData(BaseModel):
    """Значения полей мероприятия для предзаполнения формы редактирования."""

    starts_at: datetime.datetime
    ends_at: datetime.datetime | None
    location: str
    description: str
    details: str | None
    budget_per_person: decimal.Decimal | None
    seats_limit: int | None
    co_organizer_user_ids: list[int]


class EditEventContext(BaseModel):
    """Контекст формы редактирования: название проекта, участники для выбора
    со-организаторов и текущие значения полей мероприятия."""

    project_name: str
    members: list[EventFormMember]
    event: EventFormData


class UpdateEventResponse(BaseModel):
    event_id: int
    announcement_message_id: int | None
    notified_going: int


def _display_name(user: User) -> str:
    if user.last_name:
        return f"{user.first_name} {user.last_name}"
    return user.first_name


async def _active_members(
    session: AsyncSession, *, project_id: int
) -> list[tuple[ProjectMembership, User]]:
    result = await session.execute(
        select(ProjectMembership, User)
        .join(User, User.id == ProjectMembership.user_id)
        .where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.status == MembershipStatus.ACTIVE,
        )
        .order_by(User.first_name, User.id)
    )
    return [(row.ProjectMembership, row.User) for row in result]


@router.get("/events/context")
async def event_form_context(
    ctx: Annotated[ProjectContext, Depends(require_project_context)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventFormContext:
    members = await _active_members(session, project_id=ctx.project.id)
    return EventFormContext(
        project_name=ctx.project.name,
        members=[
            EventFormMember(
                user_id=user.id,
                name=_display_name(user),
                is_self=user.id == ctx.user.id,
            )
            for _, user in members
        ],
    )


@router.post("/events", status_code=status.HTTP_201_CREATED)
async def create_event(
    payload: CreateEventRequest,
    ctx: Annotated[ProjectContext, Depends(require_project_context)],
    session: Annotated[AsyncSession, Depends(get_session)],
    bot: Annotated[Bot, Depends(get_bot)],
) -> CreateEventResponse:
    members = await _active_members(session, project_id=ctx.project.id)
    members_by_id = {user.id: user for _, user in members}

    co_organizer_ids = list(dict.fromkeys(payload.co_organizer_user_ids))
    unknown = [uid for uid in co_organizer_ids if uid not in members_by_id]
    if unknown:
        raise HTTPException(status_code=422, detail="co_organizer_not_a_member")

    event = Event(
        project_id=ctx.project.id,
        description=payload.description,
        details=payload.details,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        location=payload.location,
        budget_per_person=payload.budget_per_person,
        seats_limit=payload.seats_limit,
        created_by=ctx.user.id,
    )
    session.add(event)
    await session.flush()

    for uid in co_organizer_ids:
        session.add(EventCoOrganizer(event_id=event.id, user_id=uid))

    settings = await session.get(ProjectSettings, ctx.project.id)
    timezone = settings.timezone if settings is not None else DEFAULT_TIMEZONE
    co_organizers = [members_by_id[uid] for uid in co_organizer_ids]

    announcement_message_id = await publish_event_announcement(
        bot,
        session,
        event,
        chat_id=ctx.project.tg_chat_id,
        invite_payload=ctx.project.invite_payload,
        co_organizers=co_organizers,
        going=[],
        not_going=[],
        timezone=timezone,
    )
    event.announcement_message_id = announcement_message_id
    await session.commit()

    return CreateEventResponse(
        event_id=event.id, announcement_message_id=announcement_message_id
    )


async def _load_manageable_event(
    session: AsyncSession, ctx: ProjectContext, event_id: int
) -> Event:
    """Мероприятие проекта из контекста, которое текущий пользователь вправе
    редактировать. `404 event_not_found` — чужой/несуществующий id (факт
    существования в другом проекте наружу не раскрываем), `409 event_not_editable`
    — отменено или явка уже финализирована, `403 not_an_organizer` — нет прав."""
    event = await session.get(Event, event_id)
    if event is None or event.project_id != ctx.project.id:
        raise HTTPException(status_code=404, detail="event_not_found")
    if event.status != EventStatus.PLANNED or event.attendance_finalized_at is not None:
        raise HTTPException(status_code=409, detail="event_not_editable")

    is_admin = ctx.membership.role in (MembershipRole.OWNER, MembershipRole.ADMIN)
    if not await can_manage_event(
        session, event=event, user_id=ctx.user.id, is_admin=is_admin
    ):
        raise HTTPException(status_code=403, detail="not_an_organizer")
    return event


@router.get("/events/{event_id}")
async def event_edit_context(
    event_id: int,
    ctx: Annotated[ProjectContext, Depends(require_project_context)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EditEventContext:
    event = await _load_manageable_event(session, ctx, event_id)
    members = await _active_members(session, project_id=ctx.project.id)
    co_ids = list(
        await session.scalars(
            select(EventCoOrganizer.user_id)
            .where(EventCoOrganizer.event_id == event.id)
            .order_by(EventCoOrganizer.id)
        )
    )
    return EditEventContext(
        project_name=ctx.project.name,
        members=[
            EventFormMember(
                user_id=user.id,
                name=_display_name(user),
                is_self=user.id == ctx.user.id,
            )
            for _, user in members
        ],
        event=EventFormData(
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            location=event.location,
            description=event.description,
            details=event.details,
            budget_per_person=event.budget_per_person,
            seats_limit=event.seats_limit,
            co_organizer_user_ids=co_ids,
        ),
    )


@router.put("/events/{event_id}")
async def update_event(
    event_id: int,
    payload: UpdateEventRequest,
    ctx: Annotated[ProjectContext, Depends(require_project_context)],
    session: Annotated[AsyncSession, Depends(get_session)],
    bot: Annotated[Bot, Depends(get_bot)],
) -> UpdateEventResponse:
    event = await _load_manageable_event(session, ctx, event_id)

    members = await _active_members(session, project_id=ctx.project.id)
    members_by_id = {user.id: user for _, user in members}
    co_organizer_ids = list(dict.fromkeys(payload.co_organizer_user_ids))
    unknown = [uid for uid in co_organizer_ids if uid not in members_by_id]
    if unknown:
        raise HTTPException(status_code=422, detail="co_organizer_not_a_member")

    settings = await session.get(ProjectSettings, ctx.project.id)
    timezone = settings.timezone if settings is not None else DEFAULT_TIMEZONE

    before = EventSnapshot(event)
    event.starts_at = payload.starts_at
    event.ends_at = payload.ends_at
    event.location = payload.location
    event.description = payload.description
    event.details = payload.details
    event.budget_per_person = payload.budget_per_person
    event.seats_limit = payload.seats_limit

    existing = {
        row.user_id: row
        for row in await session.scalars(
            select(EventCoOrganizer).where(EventCoOrganizer.event_id == event.id)
        )
    }
    for uid, row in existing.items():
        if uid not in co_organizer_ids:
            await session.delete(row)
    for uid in co_organizer_ids:
        if uid not in existing:
            session.add(EventCoOrganizer(event_id=event.id, user_id=uid))

    await session.flush()
    await refresh_event_announcement(bot, session, event)
    await session.commit()

    notified = 0
    notification = build_event_update_notification(before, event, timezone=timezone)
    if notification is not None:
        keyboard = build_event_update_keyboard(
            event.id,
            announcement_url=announcement_deep_link(
                ctx.project.tg_chat_id, event.announcement_message_id
            ),
        )
        notified = await notify_going_members(
            bot, session, event, text=notification, reply_markup=keyboard
        )

    return UpdateEventResponse(
        event_id=event.id,
        announcement_message_id=event.announcement_message_id,
        notified_going=notified,
    )


class CancelEventResponse(BaseModel):
    """Итог отмены мероприятия с экрана Web App (задача 2.9.3): удалось ли
    перерисовать анонс и скольким подтвердившим участие ушло уведомление."""

    announcement_ok: bool
    notified: int


@router.post("/events/{event_id}/cancel")
async def cancel_event_endpoint(
    event_id: int,
    ctx: Annotated[ProjectContext, Depends(require_project_context)],
    session: Annotated[AsyncSession, Depends(get_session)],
    bot: Annotated[Bot, Depends(get_bot)],
) -> CancelEventResponse:
    """Отмена мероприятия организатором с экрана мероприятия. Права и то, что
    мероприятие ещё можно отменить, проверяет тот же `_load_manageable_event`,
    что и `PUT /api/events/{id}` (правило 2.7): `404 event_not_found` —
    чужой/несуществующий id, `409 event_not_editable` — уже отменено или явка
    финализирована, `403 not_an_organizer` — нет прав. Дальше — общий сервис
    `cancel_event` (тот же, что у команды `/cancel_event`)."""
    event = await _load_manageable_event(session, ctx, event_id)
    settings = await session.get(ProjectSettings, ctx.project.id)
    timezone = settings.timezone if settings is not None else DEFAULT_TIMEZONE
    announcement_ok, notified = await cancel_event(
        bot, session, event, timezone=timezone
    )
    return CancelEventResponse(announcement_ok=announcement_ok, notified=notified)


class EventViewPerson(BaseModel):
    user_id: int
    name: str


class EventRsvpSummary(BaseModel):
    going_count: int
    not_going_count: int
    my_rsvp: Literal["going", "not_going"] | None


class EventView(BaseModel):
    """Мероприятие для экрана Web App (задача 2.9.2): поля + со-организаторы +
    списки RSVP + сводка + личная отметка + признак прав на управление + ссылка
    на анонс. Доступен любому активному участнику проекта (в отличие от
    `GET /api/events/{id}`, требующего прав на управление).

    Полные списки `going` / `not_going` здесь — «дом» для кнопки «полный список»
    из анонса: при переполнении лимита длины анонс сворачивает никнеймы в числа
    (TZ §4.3), а весь список смотрят на этом экране."""

    id: int
    title: str | None
    starts_at: datetime.datetime
    ends_at: datetime.datetime | None
    location: str
    description: str
    details: str | None
    budget_per_person: decimal.Decimal | None
    seats_limit: int | None
    status: str
    is_finalized: bool
    co_organizers: list[EventViewPerson]
    # Активные участники проекта, в порядке ответа (кто раньше нажал кнопку).
    going: list[EventViewPerson]
    not_going: list[EventViewPerson]
    rsvp: EventRsvpSummary
    announcement_url: str | None
    # Может ли текущий пользователь редактировать/отменять мероприятие прямо
    # сейчас — фронт по нему рисует меню «⋯» в шапке экрана.
    can_manage: bool


class RsvpRequest(BaseModel):
    status: Literal["going", "not_going"]


_RSVP_ERROR_STATUS = {
    "event_not_found": 404,
    "event_cancelled": 409,
    "event_finalized": 409,
    "not_registered": 403,
}


async def _load_project_event(
    session: AsyncSession, ctx: ProjectContext, event_id: int
) -> Event:
    """Мероприятие проекта из контекста. `404 event_not_found` — чужой id или его
    нет (существование в другом проекте наружу не раскрываем)."""
    event = await session.get(Event, event_id)
    if event is None or event.project_id != ctx.project.id:
        raise HTTPException(status_code=404, detail="event_not_found")
    return event


async def _can_manage_now(
    session: AsyncSession, ctx: ProjectContext, event: Event
) -> bool:
    """Вправе ли текущий пользователь редактировать/отменять `event` прямо
    сейчас — те же условия, что в `_load_manageable_event`."""
    if event.status != EventStatus.PLANNED or event.attendance_finalized_at is not None:
        return False
    is_admin = ctx.membership.role in (MembershipRole.OWNER, MembershipRole.ADMIN)
    return await can_manage_event(
        session, event=event, user_id=ctx.user.id, is_admin=is_admin
    )


async def _rsvp_summary(
    session: AsyncSession, *, event_id: int, user_id: int
) -> EventRsvpSummary:
    going, not_going, mine = await rsvp_summary(
        session, event_id=event_id, user_id=user_id
    )
    return EventRsvpSummary(
        going_count=going,
        not_going_count=not_going,
        my_rsvp=mine.value if mine is not None else None,
    )


@router.get("/events/{event_id}/view")
async def event_view(
    event_id: int,
    ctx: Annotated[ProjectContext, Depends(require_project_context)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventView:
    event = await _load_project_event(session, ctx, event_id)

    co_users, going_users, not_going_users = await load_announcement_participants(
        session, event
    )

    def _people(users: list[User]) -> list[EventViewPerson]:
        return [EventViewPerson(user_id=u.id, name=_display_name(u)) for u in users]

    if any(u.id == ctx.user.id for u in going_users):
        my_rsvp: Literal["going", "not_going"] | None = "going"
    elif any(u.id == ctx.user.id for u in not_going_users):
        my_rsvp = "not_going"
    else:
        my_rsvp = None

    return EventView(
        id=event.id,
        title=event.title,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        location=event.location,
        description=event.description,
        details=event.details,
        budget_per_person=event.budget_per_person,
        seats_limit=event.seats_limit,
        status=event.status.value,
        is_finalized=event.attendance_finalized_at is not None,
        co_organizers=_people(co_users),
        going=_people(going_users),
        not_going=_people(not_going_users),
        rsvp=EventRsvpSummary(
            going_count=len(going_users),
            not_going_count=len(not_going_users),
            my_rsvp=my_rsvp,
        ),
        announcement_url=announcement_deep_link(
            ctx.project.tg_chat_id, event.announcement_message_id
        ),
        can_manage=await _can_manage_now(session, ctx, event),
    )


@router.post("/events/{event_id}/rsvp")
async def event_rsvp(
    event_id: int,
    payload: RsvpRequest,
    ctx: Annotated[ProjectContext, Depends(require_project_context)],
    session: Annotated[AsyncSession, Depends(get_session)],
    bot: Annotated[Bot, Depends(get_bot)],
) -> EventRsvpSummary:
    await _load_project_event(session, ctx, event_id)
    try:
        result = await set_rsvp(
            session,
            event_id=event_id,
            tg_user_id=ctx.user.tg_user_id,
            target=RSVPStatus(payload.status),
        )
    except RsvpError as exc:
        raise HTTPException(
            status_code=_RSVP_ERROR_STATUS[exc.code], detail=exc.code
        ) from exc
    if result.changed:
        await refresh_announcement_after_rsvp(bot, session, event_id)
    return await _rsvp_summary(session, event_id=event_id, user_id=ctx.user.id)
