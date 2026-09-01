"""Домашний экран-хаб Web App (задача 2.9.1, TZ §3.8).

Кнопка-меню бота ведёт на фиксированный URL хаба без контекста проекта. Хаб по
одной проверенной `initData` (без параметра `project`) узнаёт, кто пользователь
и в каких он проектах (`GET /api/home`), а затем для каждой секции-проекта
запрашивает список мероприятий (`GET /api/projects/{payload}/events`).
"""

from __future__ import annotations

import datetime
from typing import Annotated

from aiogram.utils.web_app import WebAppInitData
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.api.context import resolve_project_context
from meetup_bot.api.webapp_auth import get_init_data, get_tg_user_id
from meetup_bot.db.session import get_session
from meetup_bot.services.events import list_project_events
from meetup_bot.services.projects import list_user_projects_with_role

router = APIRouter(prefix="/api", tags=["home"])


class HomeProject(BaseModel):
    payload: str
    name: str
    role: str


class HomeResponse(BaseModel):
    """Кто пользователь и в каких он проектах. `projects` пуст → пользователь не
    делал `/start` ни в одном чате (состояние «вы не зарегистрированы» на хабе)."""

    user_name: str
    projects: list[HomeProject]


class EventCard(BaseModel):
    id: int
    title: str | None
    starts_at: datetime.datetime
    ends_at: datetime.datetime | None
    location: str
    seats_limit: int | None
    going_count: int
    is_finalized: bool


class ProjectEventsResponse(BaseModel):
    events: list[EventCard]


def _user_name(init_data: WebAppInitData) -> str:
    user = init_data.user
    if user is None:  # pragma: no cover — гарантировано get_init_data
        return "участник"
    if user.last_name:
        return f"{user.first_name} {user.last_name}"
    return user.first_name


@router.get("/home")
async def home(
    init_data: Annotated[WebAppInitData, Depends(get_init_data)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HomeResponse:
    tg_user_id = init_data.user.id if init_data.user is not None else 0
    projects = await list_user_projects_with_role(session, tg_user_id=tg_user_id)
    return HomeResponse(
        user_name=_user_name(init_data),
        projects=[
            HomeProject(payload=project.invite_payload, name=project.name, role=role.value)
            for project, role in projects
        ],
    )


@router.get("/projects/{payload}/events")
async def project_events(
    payload: str,
    tg_user_id: Annotated[int, Depends(get_tg_user_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectEventsResponse:
    ctx = await resolve_project_context(
        session, tg_user_id=tg_user_id, invite_payload=payload
    )
    events = await list_project_events(session, project_id=ctx.project.id)
    return ProjectEventsResponse(
        events=[
            EventCard(
                id=event.id,
                title=event.title,
                starts_at=event.starts_at,
                ends_at=event.ends_at,
                location=event.location,
                seats_limit=event.seats_limit,
                going_count=going_count,
                is_finalized=event.attendance_finalized_at is not None,
            )
            for event, going_count in events
        ]
    )
