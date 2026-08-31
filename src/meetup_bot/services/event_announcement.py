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
from sqlalchemy import Select, select
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


def _format_when(
    starts_at: datetime.datetime,
    ends_at: datetime.datetime | None,
    tz: ZoneInfo,
) -> str:
    """«14 сентября, 15:00» или «14 сентября, 15:00 — 15 сентября, 12:00» —
    для уведомлений об изменении/отмене."""
    when = _format_datetime(starts_at, tz)
    if ends_at is not None:
        when += f" — {_format_datetime(ends_at, tz)}"
    return when


def announcement_deep_link(tg_chat_id: int, message_id: int | None) -> str | None:
    """Ссылка вида `https://t.me/c/<internal>/<message_id>` на анонс в
    супергруппе проекта. `None`, если анонс не публиковался или чат — не
    супергруппа (id без префикса `-100`, ссылка `t.me/c/` не сработает)."""
    if message_id is None:
        return None
    marker = "-100"
    chat = str(tg_chat_id)
    if not chat.startswith(marker):
        return None
    return f"https://t.me/c/{chat[len(marker):]}/{message_id}"


def build_event_update_keyboard(
    event_id: int, *, announcement_url: str | None
) -> InlineKeyboardMarkup:
    """Кнопки под личным уведомлением об изменении мероприятия: переход к анонсу
    (если ссылка есть) и та же пара RSVP-кнопок, что под анонсом, — чтобы можно
    было переотметиться, не открывая чат."""
    rows: list[list[InlineKeyboardButton]] = []
    if announcement_url is not None:
        rows.append(
            [InlineKeyboardButton(text="🔗 Перейти к анонсу", url=announcement_url)]
        )
    rows.append(
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
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_announcement_text(
    event: Event,
    *,
    co_organizers: list[User],
    going: list[User],
    not_going: list[User],
    timezone: str,
) -> str:
    """HTML-текст анонса: все поля мероприятия + два списка RSVP — «участвует» и
    «не участвует» — с никнеймами (TZ §4.3 «RSVP»). Третья группа (активные
    участники, ещё не нажавшие ни одну кнопку) в анонсе не показывается.

    `seats_limit` — мягкий ориентир, а не потолок: при `len(going) >= seats_limit`
    к счётчику добавляется пометка «цель набрана», но RSVP не блокируется
    (хендлер лимит не проверяет).

    Для отменённого мероприятия (`status = cancelled`, задача 2.8) оба списка
    RSVP опускаются, а вместо них снизу — выделенная пометка «Мероприятие
    отменено» (RSVP уже неактуален; кнопки снимает
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
            counter = f"✅ Участвует: {len(going)}/{event.seats_limit}"
            if len(going) >= event.seats_limit:
                counter += " — цель набрана 🎯"
            lines.append(counter)
        else:
            lines.append(f"✅ Участвует: {len(going)}")
        lines.extend(f"{i}. {_mention(u)}" for i, u in enumerate(going, start=1))

        if not_going:
            lines.append("")
            lines.append(f"❌ Не участвует: {len(not_going)}")
            lines.extend(
                f"{i}. {_mention(u)}" for i, u in enumerate(not_going, start=1)
            )

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
    `None`, если ни одно отслеживаемое поле не поменялось (тогда рассылки нет).

    Заголовок и тон зависят от того, что правили: перенос даты/времени — с
    пометкой ⚠️, смена места — 📍, прочие правки (описание/бюджет/лимит) — мягкое
    «обновили детали». Для даты и места показываем «было → стало»; текст
    описания в личку не тащим — только пометку «посмотрите в анонсе». Кнопки к
    уведомлению добавляет `build_event_update_keyboard`."""
    tz = _resolve_tz(timezone)

    when_changed = (
        before.starts_at != event.starts_at or before.ends_at != event.ends_at
    )
    location_changed = before.location != event.location
    description_changed = before.description != event.description
    budget_changed = before.budget_per_person != event.budget_per_person
    seats_changed = before.seats_limit != event.seats_limit

    if not (
        when_changed
        or location_changed
        or description_changed
        or budget_changed
        or seats_changed
    ):
        return None

    name = f"«{escape(event.title)}»" if event.title else "мероприятие"
    if when_changed:
        header = f"⚠️ <b>Перенос: {name}</b>"
    elif location_changed:
        header = f"📍 <b>Сменилось место: {name}</b>"
    else:
        header = f"✏️ <b>Обновили детали: {name}</b>"

    body: list[str] = []
    if when_changed:
        body.append(
            "🗓 Новое время: "
            f"<b>{_format_when(event.starts_at, event.ends_at, tz)}</b>"
        )
        body.append(
            f"Было: <s>{_format_when(before.starts_at, before.ends_at, tz)}</s>"
        )
    if location_changed:
        body.append(f"📍 Теперь: <b>{escape(event.location)}</b>")
        body.append(f"Было: <s>{escape(before.location)}</s>")
    if description_changed:
        body.append("📝 Поправили описание — посмотрите в анонсе")
    if budget_changed:
        if event.budget_per_person is None:
            body.append("💰 Бюджет с человека больше не указан")
        else:
            if before.budget_per_person is None:
                note = " (раньше не указан)"
            else:
                note = f" (было {_format_amount(before.budget_per_person)} ₽)"
            body.append(
                "💰 Бюджет с человека: "
                f"{_format_amount(event.budget_per_person)} ₽{note}"
            )
    if seats_changed:
        if event.seats_limit is None:
            body.append("🎟 Лимит мест снят")
        else:
            if before.seats_limit is None:
                note = " (лимит добавили)"
            else:
                note = f" (было {before.seats_limit})"
            body.append(f"🎟 Мест: {event.seats_limit}{note}")

    if when_changed or location_changed:
        footer = "Всё ещё ждём вас. Не сможете — нажмите «Не участвую» ниже."
    else:
        footer = "Дата и место прежние, действий не требуется."

    return "\n".join([header, "", *body, "", footer])


def build_event_cancelled_notification(event: Event, *, timezone: str) -> str:
    """Личное уведомление подтвердившим участие об отмене мероприятия (задача 2.8).
    В отличие от уведомления об изменении, шлётся всегда — отмена существенна."""
    tz = _resolve_tz(timezone)
    head = (
        f"«{escape(event.title)}» не состоится."
        if event.title
        else "Мероприятие не состоится."
    )
    return "\n".join(
        [
            "🚫 <b>Мероприятие отменено</b>",
            "",
            f"{head} Вы были записаны на участие — приходить не нужно.",
            "",
            f"🗓 {_format_when(event.starts_at, event.ends_at, tz)}",
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
    not_going: list[User],
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
            event,
            co_organizers=co_organizers,
            going=going,
            not_going=not_going,
            timezone=timezone,
        ),
        reply_markup=build_rsvp_keyboard(event.id),
    )
    return message.message_id


async def _announcement_participants(
    session: AsyncSession, event: Event
) -> tuple[list[User], list[User], list[User]]:
    """`(co_organizers, going, not_going)` для перерисовки анонса: со-организаторы
    в порядке добавления, ответившие — в порядке ответа (кто раньше нажал кнопку).

    Во всех трёх списках — только активные участники проекта: удалённый через
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
    def _rsvp_users(status: RSVPStatus) -> Select[tuple[User]]:
        return (
            select(User)
            .join(EventRSVP, EventRSVP.user_id == User.id)
            .join(ProjectMembership, active_member)
            .where(
                EventRSVP.event_id == event.id,
                EventRSVP.status == status,
            )
            .order_by(EventRSVP.responded_at, EventRSVP.id)
        )

    going = list(await session.scalars(_rsvp_users(RSVPStatus.GOING)))
    not_going = list(await session.scalars(_rsvp_users(RSVPStatus.NOT_GOING)))
    return co_organizers, going, not_going


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
    TZ §4.3 «RSVP»): пересчитывает счётчик подтвердивших и оба списка никнеймов
    — «участвует» и «не участвует».
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

    co_organizers, going, not_going = await _announcement_participants(session, event)
    text = build_announcement_text(
        event,
        co_organizers=co_organizers,
        going=going,
        not_going=not_going,
        timezone=timezone,
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
