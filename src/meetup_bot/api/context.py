"""Контекст проекта для ручек Web App (`/api/*`).

Формы Mini App всегда открываются в контексте конкретного проекта: бот кладёт
`project` (= `Project.invite_payload`) в query-параметр URL кнопки (TZ §3.2 п.4,
§3.8). Здесь — FastAPI-зависимость, которая по проверенной `initData`
(`get_tg_user_id`) и этому параметру находит активное `ProjectMembership`
пользователя и отдаёт ручке уже сверенный `(project, user)`.

Изоляция арендаторов (TZ §6.1): `project_id` берётся только отсюда, из
подтверждённого членства, а не из произвольного значения клиента.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from aiogram import Bot
from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.api.webapp_auth import get_tg_user_id
from meetup_bot.db.enums import MembershipStatus
from meetup_bot.db.models import Project, ProjectMembership, User
from meetup_bot.db.session import get_session


@dataclass(frozen=True)
class ProjectContext:
    """Проверенный контекст запроса Web App: проект и его активный участник."""

    project: Project
    user: User
    membership: ProjectMembership


async def require_project_context(
    tg_user_id: Annotated[int, Depends(get_tg_user_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
    project: Annotated[str | None, Query()] = None,
) -> ProjectContext:
    """Зависимость: `(project, user, membership)` для текущего запроса.

    - нет параметра `project` → `400 missing_project`;
    - проект не найден, пользователь не делал `/start` или не активный участник
      → `403 not_registered` (существование проекта наружу не раскрываем —
      один и тот же ответ на все три случая, TZ §3.2 п.4).
    """
    if not project:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="missing_project"
        )

    row = (
        await session.execute(
            select(Project, ProjectMembership, User)
            .join(ProjectMembership, ProjectMembership.project_id == Project.id)
            .join(User, User.id == ProjectMembership.user_id)
            .where(
                Project.invite_payload == project,
                Project.is_active.is_(True),
                User.tg_user_id == tg_user_id,
                ProjectMembership.status == MembershipStatus.ACTIVE,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="not_registered"
        )

    return ProjectContext(
        project=row.Project, user=row.User, membership=row.ProjectMembership
    )


def get_bot(request: Request) -> Bot:
    """Зависимость: экземпляр `aiogram.Bot` приложения (создаётся в lifespan,
    `app.state.bot`). Нужен ручке создания мероприятия для публикации анонса."""
    bot: Bot = request.app.state.bot
    return bot
