"""Обработка нажатий RSVP под анонсом мероприятия и живое обновление анонса
(TZ §4.3 «RSVP», задача 2.6).

`callback_data` кнопок анонса — `rsvp:<event_id>:<going|not_going>` (см.
`services/event_announcement.py`). Нажатие → upsert `EventRSVP` по
(`event_id`, `user_id`) с `updated_by = user_id` (самоотметка). Повторное
нажатие переключает статус, а не копит записи. Каждое изменение сразу правит
текст анонса (`refresh_event_announcement`): счётчик подтвердивших и их никнеймы.
Ответ на нажатие — короткое всплывающее подтверждение, без сообщения в чат.

Постфактум-правка чужого RSVP организатором/админом (`updated_by != user_id`) —
отдельный сценарий (Web App, задача 3.2), не этот хендлер.
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.enums import EventStatus, MembershipStatus, RSVPStatus
from meetup_bot.db.models import Event, EventRSVP, ProjectMembership, User
from meetup_bot.services.event_announcement import (
    RSVP_CALLBACK_PREFIX,
    refresh_event_announcement,
)

_NOT_REGISTERED_TEXT = (
    "Сначала зарегистрируйтесь в проекте по ссылке из поста регистрации."
)
_EVENT_GONE_TEXT = "Мероприятие не найдено."
_EVENT_CANCELLED_TEXT = "Мероприятие отменено."
_EVENT_FINALIZED_TEXT = "Явка уже зафиксирована — ответ больше не изменить."
_GOING_TEXT = "Вы участвуете ✅"
_NOT_GOING_TEXT = "Вы не участвуете ❌"


def _parse_callback(data: str) -> tuple[int, RSVPStatus] | None:
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != RSVP_CALLBACK_PREFIX:
        return None
    try:
        event_id = int(parts[1])
        target = RSVPStatus(parts[2])
    except ValueError:
        return None
    return event_id, target


def create_router() -> Router:
    router = Router(name="rsvp")

    @router.callback_query(F.data.startswith(f"{RSVP_CALLBACK_PREFIX}:"))
    async def on_rsvp(
        callback: CallbackQuery, session: AsyncSession, bot: Bot
    ) -> None:
        if callback.data is None or callback.from_user is None:
            return
        parsed = _parse_callback(callback.data)
        if parsed is None:
            await callback.answer()
            return
        event_id, target = parsed

        event = await session.get(Event, event_id)
        if event is None:
            await callback.answer(_EVENT_GONE_TEXT, show_alert=True)
            return
        if event.status == EventStatus.CANCELLED:
            await callback.answer(_EVENT_CANCELLED_TEXT, show_alert=True)
            return
        # После финализации явки RSVP правит только организатор через Web App
        # (TZ §3.4 п.1, задача 3.2) — самоотметка кнопкой уже недоступна.
        if event.attendance_finalized_at is not None:
            await callback.answer(_EVENT_FINALIZED_TEXT, show_alert=True)
            return

        # Кнопку под групповым анонсом видит весь чат, поэтому членство
        # проверяем на каждый клик, а не доверяем факту нажатия.
        user = await session.scalar(
            select(User)
            .join(ProjectMembership, ProjectMembership.user_id == User.id)
            .where(
                ProjectMembership.project_id == event.project_id,
                ProjectMembership.status == MembershipStatus.ACTIVE,
                User.tg_user_id == callback.from_user.id,
            )
        )
        if user is None:
            await callback.answer(_NOT_REGISTERED_TEXT, show_alert=True)
            return

        rsvp = await session.scalar(
            select(EventRSVP).where(
                EventRSVP.event_id == event_id,
                EventRSVP.user_id == user.id,
            )
        )
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

        await callback.answer(
            _GOING_TEXT if target == RSVPStatus.GOING else _NOT_GOING_TEXT
        )

    return router
