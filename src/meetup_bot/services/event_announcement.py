"""Публикация и текст анонса мероприятия в групповом чате (TZ §4.3 «Создание», п. 4).

Анонс уходит в топик категории `events` (`resolve_thread_id`), под ним — две
inline-кнопки «✅ Участвую» / «❌ Не участвую». `callback_data` кнопок —
`rsvp:<event_id>:<going|not_going>`; сам хендлер нажатий и живое обновление
текста — задача 2.6, здесь только первичная публикация.
"""

from __future__ import annotations

import datetime
import decimal
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.enums import RSVPStatus, TopicCategory
from meetup_bot.db.models import Event, User
from meetup_bot.services.projects import resolve_thread_id

RSVP_CALLBACK_PREFIX = "rsvp"

_MONTHS_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def rsvp_callback_data(event_id: int, status: RSVPStatus) -> str:
    return f"{RSVP_CALLBACK_PREFIX}:{event_id}:{status.value}"


def build_rsvp_keyboard(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Участвую",
                    callback_data=rsvp_callback_data(event_id, RSVPStatus.GOING),
                ),
                InlineKeyboardButton(
                    text="❌ Не участвую",
                    callback_data=rsvp_callback_data(event_id, RSVPStatus.NOT_GOING),
                ),
            ]
        ]
    )


def _mention(user: User) -> str:
    """`@username`, либо text-mention по `tg_user_id` для скрывших юзернейм —
    как в `/all` (TZ §4.2)."""
    if user.username:
        return f"@{escape(user.username)}"
    return f'<a href="tg://user?id={user.tg_user_id}">{escape(user.first_name)}</a>'


def _resolve_tz(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone)
    except Exception:  # noqa: BLE001 — битая строка таймзоны не должна ронять публикацию
        return ZoneInfo("UTC")


def _format_datetime(value: datetime.datetime, tz: ZoneInfo) -> str:
    local = value.astimezone(tz)
    return f"{local.day} {_MONTHS_GENITIVE[local.month - 1]}, {local:%H:%M}"


def _format_amount(value: decimal.Decimal) -> str:
    return f"{value.normalize():f}"


def build_announcement_text(
    event: Event,
    *,
    co_organizers: list[User],
    going: list[User],
    timezone: str,
) -> str:
    """HTML-текст анонса: все поля мероприятия + счётчик подтвердивших и их
    никнеймы (TZ §4.3 «RSVP»). Список «не участвую» в анонсе не показывается."""
    tz = _resolve_tz(timezone)

    lines: list[str] = []
    if event.title:
        lines.append(f"<b>{escape(event.title)}</b>")
        lines.append("")

    when = f"🗓 {_format_datetime(event.starts_at, tz)}"
    if event.ends_at is not None:
        when += f" — {_format_datetime(event.ends_at, tz)}"
    lines.append(when)
    lines.append(f"📍 {escape(event.location)}")
    lines.append("")
    lines.append(escape(event.description))

    extras: list[str] = []
    if event.budget_per_person is not None:
        extras.append(f"💰 Бюджет с человека: {_format_amount(event.budget_per_person)} ₽")
    if event.seats_limit is not None:
        extras.append(f"🎟 Мест: {event.seats_limit}")
    if extras:
        lines.append("")
        lines.extend(extras)

    if co_organizers:
        lines.append("")
        lines.append("Организуют: " + ", ".join(_mention(u) for u in co_organizers))

    lines.append("")
    if event.seats_limit is not None:
        lines.append(f"✅ Участвует: {len(going)}/{event.seats_limit}")
    else:
        lines.append(f"✅ Участвует: {len(going)}")
    if going:
        lines.append(", ".join(_mention(u) for u in going))

    return "\n".join(lines)


async def publish_event_announcement(
    bot: Bot,
    session: AsyncSession,
    event: Event,
    *,
    chat_id: int,
    co_organizers: list[User],
    going: list[User],
    timezone: str,
) -> int:
    """Публикует анонс в топик категории `events` проекта и возвращает
    `message_id` (его вызывающий кладёт в `Event.announcement_message_id`)."""
    thread_id = await resolve_thread_id(
        session, project_id=event.project_id, category=TopicCategory.EVENTS
    )
    message = await bot.send_message(
        chat_id=chat_id,
        message_thread_id=thread_id,
        text=build_announcement_text(
            event, co_organizers=co_organizers, going=going, timezone=timezone
        ),
        reply_markup=build_rsvp_keyboard(event.id),
    )
    return message.message_id
