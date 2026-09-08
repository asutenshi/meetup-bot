"""Пометка «бот заблокирован пользователем» (TZ §6.2, задача 5.1 «Граничные
случаи»).

Когда человек блокирует бота в личке, Telegram отвечает `403 bot was blocked by
the user` на любую отправку и присылает `my_chat_member` с новым статусом
`kicked`. Пока стоит `User.bot_blocked_at`, worker не тратит проходы на личные
напоминания/эскалации этому человеку (см. `scheduler/absence_reminder.py`,
`scheduler/escalation.py`). Метка снимается, как только человек снова доступен:
разблокировал (`my_chat_member` → `member`), написал боту (`get_or_create_user`)
или успешно получил сообщение.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.models import User


async def mark_bot_blocked(
    session: AsyncSession, *, tg_user_id: int, now: datetime | None = None
) -> None:
    """Проставляет `User.bot_blocked_at`, если ещё не стоит (важен первый момент,
    когда блокировка обнаружена). Нет такого `User` — no-op. `commit` — за
    вызывающим."""
    user = await session.scalar(select(User).where(User.tg_user_id == tg_user_id))
    if user is not None and user.bot_blocked_at is None:
        user.bot_blocked_at = now or datetime.now(UTC)


async def clear_bot_blocked(session: AsyncSession, *, tg_user_id: int) -> None:
    """Снимает `User.bot_blocked_at` — человек снова доступен. Нет такого `User`
    или метка и так снята — no-op. `commit` — за вызывающим."""
    user = await session.scalar(select(User).where(User.tg_user_id == tg_user_id))
    if user is not None and user.bot_blocked_at is not None:
        user.bot_blocked_at = None
