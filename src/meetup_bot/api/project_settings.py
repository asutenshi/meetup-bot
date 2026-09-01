"""Web App-экран настроек проекта — задача 4.5.

Owner/admin открывает экран с хаба (`GET /api/projects/{payload}/settings`),
правит те же параметры `ProjectSettings`, что и команда `/settings`, плюс
`all_command_throttle_seconds`, и сохраняет их одной формой (`PUT`). Значения
валидируются общим `services.project_settings` — правила диапазонов и разбора
таймзоны живут в одном месте с командой.

Контекст проекта — по `payload` из пути через `resolve_project_context` (как
`GET /api/projects/{payload}/events`), затем проверка роли: не owner/admin →
`403 not_an_admin`. Не участник / неизвестный проект → `403 not_registered`
(существование проекта наружу не раскрываем).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.api.context import ProjectContext, resolve_project_context
from meetup_bot.api.webapp_auth import get_tg_user_id
from meetup_bot.db.enums import MembershipRole
from meetup_bot.db.models import ProjectSettings
from meetup_bot.db.session import get_session
from meetup_bot.services.project_settings import (
    EDITABLE_SETTINGS,
    SettingValueError,
    apply_settings,
    parse_setting,
)
from meetup_bot.services.projects import get_or_create_project_settings

router = APIRouter(prefix="/api", tags=["project-settings"])


class SettingField(BaseModel):
    """Описание одного поля формы — фронт рисует подпись и границы из него, без
    хардкода."""

    attr: str
    describe: str
    kind: str
    min: int | None
    max: int | None


class ProjectSettingsResponse(BaseModel):
    project_name: str
    reminder_days_threshold: int
    missed_events_escalation_count: int
    reminder_send_hour: int
    all_command_throttle_seconds: int
    timezone: str
    fields: list[SettingField]


class ProjectSettingsUpdate(BaseModel):
    """Вся форма целиком — фронт всегда шлёт все поля."""

    reminder_days_threshold: int
    missed_events_escalation_count: int
    reminder_send_hour: int
    all_command_throttle_seconds: int
    timezone: str


_FIELDS: list[SettingField] = [
    SettingField(
        attr=spec.attr,
        describe=spec.describe,
        kind=spec.kind,
        min=spec.minimum,
        max=spec.maximum,
    )
    for spec in EDITABLE_SETTINGS
]


async def _require_admin_context(
    session: AsyncSession, *, tg_user_id: int, payload: str
) -> ProjectContext:
    ctx = await resolve_project_context(
        session, tg_user_id=tg_user_id, invite_payload=payload
    )
    if ctx.membership.role not in (MembershipRole.OWNER, MembershipRole.ADMIN):
        raise HTTPException(status_code=403, detail="not_an_admin")
    return ctx


def _response(project_name: str, settings: ProjectSettings) -> ProjectSettingsResponse:
    return ProjectSettingsResponse(
        project_name=project_name,
        reminder_days_threshold=settings.reminder_days_threshold,
        missed_events_escalation_count=settings.missed_events_escalation_count,
        reminder_send_hour=settings.reminder_send_hour,
        all_command_throttle_seconds=settings.all_command_throttle_seconds,
        timezone=settings.timezone,
        fields=_FIELDS,
    )


@router.get("/projects/{payload}/settings")
async def get_project_settings(
    payload: str,
    tg_user_id: Annotated[int, Depends(get_tg_user_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectSettingsResponse:
    ctx = await _require_admin_context(session, tg_user_id=tg_user_id, payload=payload)
    settings = await get_or_create_project_settings(session, project_id=ctx.project.id)
    await session.commit()
    return _response(ctx.project.name, settings)


@router.put("/projects/{payload}/settings")
async def update_project_settings(
    payload: str,
    body: ProjectSettingsUpdate,
    tg_user_id: Annotated[int, Depends(get_tg_user_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectSettingsResponse:
    ctx = await _require_admin_context(session, tg_user_id=tg_user_id, payload=payload)
    settings = await get_or_create_project_settings(session, project_id=ctx.project.id)

    parsed: dict[str, int | str] = {}
    for attr, value in body.model_dump().items():
        try:
            parsed[attr] = parse_setting(attr, str(value))
        except SettingValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "invalid_setting",
                    "field": attr,
                    "message": str(exc),
                },
            ) from exc

    apply_settings(settings, parsed)
    await session.commit()
    return _response(ctx.project.name, settings)
