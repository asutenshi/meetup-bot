"""Самоотметка RSVP: общий сервис для кнопок под анонсом (задача 2.6) и экрана
мероприятия в Web App (задача 2.9.2).

`set_rsvp` держит всю логику одной точкой: проверки (мероприятие существует, не
отменено, явка не финализирована, вызывающий — активный участник проекта), upsert
`EventRSVP` с `updated_by = user_id` (самоотметка), живое обновление анонса и
`commit`. Повторное нажатие «❌ Не участвую» у уже отмеченного `not_going` снимает
отметку целиком — строка удаляется, человек возвращается в группу «ещё думает».

Постфактум-правка чужого RSVP организатором (`updated_by != user_id`) — отдельный
сценарий (задача 3.2), здесь не поддерживается.
"""

from __future__ import annotations

import enum

from aiogram import Bot
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.enums import EventStatus, MembershipStatus, RSVPStatus
from meetup_bot.db.models import Event, EventRSVP, ProjectMembership, User
from meetup_bot.services.event_announcement import refresh_event_announcement


class RsvpOutcome(enum.Enum):
    """Чем закончилась самоотметка — для сообщения пользователю."""

    GOING = "going"
    NOT_GOING = "not_going"
    CLEARED = "cleared"


class RsvpError(Exception):
    """Отметку поставить нельзя. `code` — машиночитаемая причина, её же отдаёт
    API в `detail` (`event_not_found` / `event_cancelled` / `event_finalized` /
    `not_registered`)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_RSVP_START_TARGET = {RSVPStatus.GOING: "g", RSVPStatus.NOT_GOING: "n"}
_RSVP_START_TARGET_REV = {code: status for status, code in _RSVP_START_TARGET.items()}


def build_rsvp_start_payload(
    *, invite_payload: str, event_id: int, target: RSVPStatus
) -> str:
    """`<invite_payload>_<event_id>_<g|n>` — payload для deep-link
    `t.me/<bot>?start=…`, которым незарегистрированного участника из-под RSVP-кнопки
    анонса уводят в личку бота: `/start` по такому payload регистрирует человека в
    проекте мероприятия и сразу ставит этот RSVP (см.
    `bot/handlers/start.py`). Разбирается [[parse_rsvp_start_payload]]."""
    return f"{invite_payload}_{event_id}_{_RSVP_START_TARGET[target]}"


def parse_rsvp_start_payload(payload: str) -> tuple[str, int, RSVPStatus] | None:
    """Разбирает payload, собранный [[build_rsvp_start_payload]], в
    `(invite_payload, event_id, target)`. `None`, если формат не подходит — тогда
    вызывающий трактует аргумент `/start` как обычный invite-payload.

    Режем справа (`rsplit("_", 2)`): `invite_payload` — это
    `secrets.token_urlsafe`, он сам может содержать `_` и `-`, а вот `event_id`
    (только цифры) и код цели (`g`/`n`) — нет."""
    parts = payload.rsplit("_", 2)
    if len(parts) != 3:
        return None
    invite_payload, raw_event_id, raw_target = parts
    if (
        not invite_payload
        or not raw_event_id.isdigit()
        or raw_target not in _RSVP_START_TARGET_REV
    ):
        return None
    return invite_payload, int(raw_event_id), _RSVP_START_TARGET_REV[raw_target]


async def rsvp_summary(
    session: AsyncSession, *, event_id: int, user_id: int
) -> tuple[int, int, RSVPStatus | None]:
    """`(going_count, not_going_count, my_rsvp)` по мероприятию — сводка для
    экрана мероприятия (`GET /api/events/{id}/view`, `POST …/rsvp`)."""
    counts = dict(
        (row[0], row[1])
        for row in await session.execute(
            select(EventRSVP.status, func.count())
            .where(EventRSVP.event_id == event_id)
            .group_by(EventRSVP.status)
        )
    )
    mine = await session.scalar(
        select(EventRSVP.status).where(
            EventRSVP.event_id == event_id, EventRSVP.user_id == user_id
        )
    )
    return (
        counts.get(RSVPStatus.GOING, 0),
        counts.get(RSVPStatus.NOT_GOING, 0),
        mine,
    )


async def set_rsvp(
    bot: Bot,
    session: AsyncSession,
    *,
    event_id: int,
    tg_user_id: int,
    target: RSVPStatus,
) -> RsvpOutcome:
    """Самоотметка участника `tg_user_id` на мероприятие `event_id`.

    Бросает `RsvpError`, если отметиться нельзя. Иначе делает upsert, при
    изменении статуса перерисовывает анонс и коммитит транзакцию.
    """
    event = await session.get(Event, event_id)
    if event is None:
        raise RsvpError("event_not_found")
    if event.status == EventStatus.CANCELLED:
        raise RsvpError("event_cancelled")
    # После финализации явки RSVP правит только организатор через Web App
    # (TZ §3.4 п.1, задача 3.2) — самоотметка уже недоступна.
    if event.attendance_finalized_at is not None:
        raise RsvpError("event_finalized")

    # Активное членство в проекте мероприятия проверяем здесь, а не доверяем
    # факту вызова: кнопку под анонсом видит весь чат.
    user = await session.scalar(
        select(User)
        .join(ProjectMembership, ProjectMembership.user_id == User.id)
        .where(
            ProjectMembership.project_id == event.project_id,
            ProjectMembership.status == MembershipStatus.ACTIVE,
            User.tg_user_id == tg_user_id,
        )
    )
    if user is None:
        raise RsvpError("not_registered")

    rsvp = await session.scalar(
        select(EventRSVP).where(
            EventRSVP.event_id == event_id,
            EventRSVP.user_id == user.id,
        )
    )
    # Повторный клик по «❌ Не участвую» у уже отмеченного not_going снимает
    # отметку: строку удаляем, человек возвращается в «ещё думает». Для
    # «✅ Участвую» такого нет — повторный клик остаётся идемпотентным.
    if (
        rsvp is not None
        and target == RSVPStatus.NOT_GOING
        and rsvp.status == RSVPStatus.NOT_GOING
    ):
        await session.delete(rsvp)
        await session.flush()
        await refresh_event_announcement(bot, session, event)
        await session.commit()
        return RsvpOutcome.CLEARED

    changed = rsvp is None or rsvp.status != target
    if rsvp is None:
        session.add(
            EventRSVP(
                event_id=event_id,
                user_id=user.id,
                status=target,
                updated_by=user.id,
            )
        )
    else:
        rsvp.status = target
        rsvp.updated_by = user.id

    if changed:
        await session.flush()
        await refresh_event_announcement(bot, session, event)
    await session.commit()

    return RsvpOutcome.GOING if target == RSVPStatus.GOING else RsvpOutcome.NOT_GOING
