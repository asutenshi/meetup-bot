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
from typing import Annotated

from aiogram import Bot
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.api.context import ProjectContext, get_bot, require_project_context
from meetup_bot.db.enums import MembershipStatus
from meetup_bot.db.models import Event, EventCoOrganizer, ProjectMembership, ProjectSettings, User
from meetup_bot.db.session import get_session
from meetup_bot.services.event_announcement import publish_event_announcement

router = APIRouter(prefix="/api", tags=["events"])

_DEFAULT_TIMEZONE = "Europe/Moscow"


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
    description: str = Field(min_length=1, max_length=4000)
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

    @model_validator(mode="after")
    def _ends_after_starts(self) -> CreateEventRequest:
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class CreateEventResponse(BaseModel):
    event_id: int
    announcement_message_id: int | None


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
    timezone = settings.timezone if settings is not None else _DEFAULT_TIMEZONE
    co_organizers = [members_by_id[uid] for uid in co_organizer_ids]

    announcement_message_id = await publish_event_announcement(
        bot,
        session,
        event,
        chat_id=ctx.project.tg_chat_id,
        co_organizers=co_organizers,
        going=[],
        timezone=timezone,
    )
    event.announcement_message_id = announcement_message_id
    await session.commit()

    return CreateEventResponse(
        event_id=event.id, announcement_message_id=announcement_message_id
    )
