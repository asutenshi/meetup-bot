"""Публикация и текст анонса мероприятия в групповом чате (TZ §4.3 «Создание», п. 4).

Анонс уходит в топик категории `events` (`resolve_thread_id`), под ним — две
inline-кнопки «✅ Участвую» / «❌ Не участвую». `callback_data` кнопок —
`rsvp:<event_id>:<going|not_going>`. Хендлер нажатий — `bot/handlers/rsvp.py`
(задача 2.6); живое обновление текста при каждом нажатии — `refresh_event_announcement`.
"""

from __future__ import annotations

import datetime
import decimal
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.enums import EventStatus, MembershipStatus, RSVPStatus, TopicCategory
from meetup_bot.db.models import (
    Event,
    EventCoOrganizer,
    EventRSVP,
    Project,
    ProjectMembership,
    ProjectSettings,
    User,
)
from meetup_bot.services.projects import resolve_thread_id

RSVP_CALLBACK_PREFIX = "rsvp"

DEFAULT_TIMEZONE = "Europe/Moscow"

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


def format_short_datetime(value: datetime.datetime, timezone: str) -> str:
    """«14 сентября, 15:00» в таймзоне проекта — для коротких подписей (кнопки
    списка `/edit_event`, уведомления об изменениях)."""
    return _format_datetime(value, _resolve_tz(timezone))


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
    никнеймы (TZ §4.3 «RSVP»). Список «не участвую» в анонсе не показывается.

    Для отменённого мероприятия (`status = cancelled`, задача 2.8) блок со
    счётчиком подтвердивших опускается, а вместо него снизу — выделенная пометка
    «Мероприятие отменено» (RSVP уже неактуален; кнопки снимает
    `refresh_event_announcement`)."""
    tz = _resolve_tz(timezone)
    cancelled = event.status == EventStatus.CANCELLED

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

    if cancelled:
        lines.append("")
        lines.append("🚫 <b>Мероприятие отменено</b>")
    else:
        lines.append("")
        if event.seats_limit is not None:
            lines.append(f"✅ Участвует: {len(going)}/{event.seats_limit}")
        else:
            lines.append(f"✅ Участвует: {len(going)}")
        lines.extend(f"{i}. {_mention(u)}" for i, u in enumerate(going, start=1))

    return "\n".join(lines)


class EventSnapshot:
    """Значения полей мероприятия, за изменением которых следит уведомление
    подтвердившим (TZ §4.3 «Редактирование»). Снимается до применения правок."""

    __slots__ = (
        "starts_at",
        "ends_at",
        "location",
        "description",
        "budget_per_person",
        "seats_limit",
    )

    def __init__(self, event: Event) -> None:
        self.starts_at = event.starts_at
        self.ends_at = event.ends_at
        self.location = event.location
        self.description = event.description
        self.budget_per_person = event.budget_per_person
        self.seats_limit = event.seats_limit


def build_event_update_notification(
    before: EventSnapshot, event: Event, *, timezone: str
) -> str | None:
    """Личное уведомление подтвердившим участие: что изменилось в мероприятии.
    `None`, если ни одно отслеживаемое поле не поменялось (тогда рассылки нет)."""
    tz = _resolve_tz(timezone)
    changes: list[str] = []

    if before.starts_at != event.starts_at or before.ends_at != event.ends_at:
        when = _format_datetime(event.starts_at, tz)
        if event.ends_at is not None:
            when += f" — {_format_datetime(event.ends_at, tz)}"
        changes.append(f"🗓 Когда: {when}")
    if before.location != event.location:
        changes.append(f"📍 Где: {escape(event.location)}")
    if before.description != event.description:
        changes.append(f"📝 Описание: {escape(event.description)}")
    if before.budget_per_person != event.budget_per_person:
        if event.budget_per_person is None:
            changes.append("💰 Бюджет с человека больше не указан")
        else:
            changes.append(
                f"💰 Бюджет с человека: {_format_amount(event.budget_per_person)} ₽"
            )
    if before.seats_limit != event.seats_limit:
        if event.seats_limit is None:
            changes.append("🎟 Лимит мест снят")
        else:
            changes.append(f"🎟 Мест: {event.seats_limit}")

    if not changes:
        return None

    title = event.title or "мероприятие"
    lines = [f"Изменилось {escape(title)}, вы записаны на участие:", ""]
    lines.extend(changes)
    return "\n".join(lines)


def build_event_cancelled_notification(event: Event, *, timezone: str) -> str:
    """Личное уведомление подтвердившим участие об отмене мероприятия (задача 2.8).
    В отличие от уведомления об изменении, шлётся всегда — отмена существенна."""
    tz = _resolve_tz(timezone)
    title = event.title or "мероприятие"
    when = _format_datetime(event.starts_at, tz)
    if event.ends_at is not None:
        when += f" — {_format_datetime(event.ends_at, tz)}"
    return "\n".join(
        [
            f"🚫 Отменено {escape(title)}, вы были записаны на участие:",
            "",
            f"🗓 {when}",
            f"📍 {escape(event.location)}",
        ]
    )


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


async def _announcement_participants(
    session: AsyncSession, event: Event
) -> tuple[list[User], list[User]]:
    """`(co_organizers, going)` для перерисовки анонса: со-организаторы в порядке
    добавления, подтвердившие — в порядке ответа (кто раньше нажал «Участвую»).

    В обоих списках — только активные участники проекта: удалённый через
    `/remove_member` человек пропадает из анонса при ближайшей перерисовке
    (а `refresh_member_announcements` вызывает её сразу после удаления)."""
    active_member = (
        (ProjectMembership.user_id == User.id)
        & (ProjectMembership.project_id == event.project_id)
        & (ProjectMembership.status == MembershipStatus.ACTIVE)
    )
    co_organizers = list(
        await session.scalars(
            select(User)
            .join(EventCoOrganizer, EventCoOrganizer.user_id == User.id)
            .join(ProjectMembership, active_member)
            .where(EventCoOrganizer.event_id == event.id)
            .order_by(EventCoOrganizer.id)
        )
    )
    going = list(
        await session.scalars(
            select(User)
            .join(EventRSVP, EventRSVP.user_id == User.id)
            .join(ProjectMembership, active_member)
            .where(
                EventRSVP.event_id == event.id,
                EventRSVP.status == RSVPStatus.GOING,
            )
            .order_by(EventRSVP.responded_at, EventRSVP.id)
        )
    )
    return co_organizers, going


async def refresh_member_announcements(
    bot: Bot, session: AsyncSession, *, project_id: int, user_id: int
) -> None:
    """Перерисовывает анонсы всех ещё не финализированных мероприятий проекта,
    где `user_id` значится подтвердившим (`EventRSVP.status = going`). Нужно после
    удаления участника из проекта (`/remove_member`), чтобы он сразу пропал из
    списка «Участвует», а не висел там до следующего чужого нажатия.

    Ошибку Bot API по конкретному анонсу (сообщение удалили, бот потерял права)
    глотаем — удаление участника не должно падать из-за неправимого анонса."""
    events = await session.scalars(
        select(Event)
        .join(EventRSVP, EventRSVP.event_id == Event.id)
        .where(
            Event.project_id == project_id,
            Event.status == EventStatus.PLANNED,
            Event.attendance_finalized_at.is_(None),
            EventRSVP.user_id == user_id,
            EventRSVP.status == RSVPStatus.GOING,
        )
    )
    for event in events:
        try:
            await refresh_event_announcement(bot, session, event)
        except TelegramAPIError:
            continue


async def refresh_event_announcement(
    bot: Bot, session: AsyncSession, event: Event
) -> bool:
    """Живое обновление анонса (`editMessageText` по `announcement_message_id`,
    TZ §4.3 «RSVP»): пересчитывает счётчик подтвердивших и список их никнеймов.
    Используется хендлером RSVP (задача 2.6); в дальнейшем — редактированием/
    отменой мероприятия (2.7–2.8) и постфактум-корректировкой RSVP (3.2).

    Возвращает `True`, если анонс удалось перерисовать (или он и так был в
    нужном состоянии), `False` — если публикации не было
    (`announcement_message_id is None`) или проект пропал. `TelegramBadRequest`
    «message is not modified» гасится — параллельное нажатие могло уже привести
    анонс в то же состояние.

    У отменённого мероприятия (задача 2.8) inline-кнопки RSVP убираются —
    отмечаться уже незачем.
    """
    if event.announcement_message_id is None:
        return False

    project = await session.get(Project, event.project_id)
    if project is None:
        return False
    settings = await session.get(ProjectSettings, event.project_id)
    timezone = settings.timezone if settings is not None else DEFAULT_TIMEZONE

    co_organizers, going = await _announcement_participants(session, event)
    text = build_announcement_text(
        event, co_organizers=co_organizers, going=going, timezone=timezone
    )
    keyboard = (
        None
        if event.status == EventStatus.CANCELLED
        else build_rsvp_keyboard(event.id)
    )
    try:
        await bot.edit_message_text(
            text=text,
            chat_id=project.tg_chat_id,
            message_id=event.announcement_message_id,
            reply_markup=keyboard,
        )
    except TelegramBadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise
    return True
