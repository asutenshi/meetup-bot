"""Обработка нажатий RSVP под анонсом мероприятия и живое обновление анонса
(TZ §4.3 «RSVP», задача 2.6).

`callback_data` кнопок анонса — `rsvp:<event_id>:<going|not_going>` (см.
`services/event_announcement.py`). Вся логика — upsert `EventRSVP` по
(`event_id`, `user_id`) с `updated_by = user_id`, проверки и перерисовка анонса —
в `services/rsvp.py::set_rsvp` (общий код с экраном мероприятия в Web App,
задача 2.9.2). Здесь только разбор `callback_data` и перевод результата в
короткое всплывающее подтверждение.

Постфактум-правка чужого RSVP организатором/админом (`updated_by != user_id`) —
отдельный сценарий (Web App, задача 3.2), не этот хендлер.
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.enums import RSVPStatus
from meetup_bot.services.event_announcement import RSVP_CALLBACK_PREFIX
from meetup_bot.services.rsvp import RsvpError, RsvpOutcome, set_rsvp

_ERROR_TEXT = {
    "event_not_found": "Мероприятие не найдено.",
    "event_cancelled": "Мероприятие отменено.",
    "event_finalized": "Явка уже зафиксирована — ответ больше не изменить.",
    "not_registered": (
        "Сначала зарегистрируйтесь в проекте по ссылке из поста регистрации."
    ),
}
_OUTCOME_TEXT = {
    RsvpOutcome.GOING: "Вы участвуете ✅",
    RsvpOutcome.NOT_GOING: "Вы не участвуете ❌",
    RsvpOutcome.CLEARED: "Отметка снята — вы пока не ответили 🤔",
}


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

        try:
            outcome = await set_rsvp(
                bot,
                session,
                event_id=event_id,
                tg_user_id=callback.from_user.id,
                target=target,
            )
        except RsvpError as exc:
            await callback.answer(_ERROR_TEXT[exc.code], show_alert=True)
            return

        await callback.answer(_OUTCOME_TEXT[outcome])

    return router
