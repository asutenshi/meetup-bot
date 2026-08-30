"""`/cancel_event` — отмена мероприятия из приватного чата с ботом (задача 2.8).

Как и `/edit_event`, работает только в личке (все точки входа в управление
мероприятием — из лички, TZ §3.8). Бот присылает список мероприятий, которые
вызвавший вправе отменить (организатор/со-организатор по `EventCoOrganizer`,
либо, если строк нет, — создатель или админ проекта), у каждого — inline-кнопка;
нажатие → подтверждение → `Event.status = cancelled`. Анонс перерисовывается:
RSVP-кнопки и список участников убираются, снизу — выделенная пометка
«Мероприятие отменено»; подтвердившим участие уходит личное уведомление. Право
проверяется повторно на каждом шаге callback-цепочки.

Если анонс перерисовать не удалось (сообщение старое/удалено, бот потерял
права, публикации не было) — отмена всё равно применяется, а вызвавшему в ответ
добавляется строка с просьбой поправить анонс вручную.

Действие «отменить» в форме редактирования (Mini App) — альтернатива из TZ §4.3,
здесь не реализуется: командной точки входа достаточно.
"""

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.enums import EventStatus
from meetup_bot.db.models import Event, ProjectSettings
from meetup_bot.services.event_announcement import (
    DEFAULT_TIMEZONE,
    build_event_cancelled_notification,
    format_short_datetime,
    refresh_event_announcement,
)
from meetup_bot.services.events import (
    can_manage_event,
    list_manageable_events,
    notify_going_members,
    resolve_member_user_id,
    user_is_project_admin,
)
from meetup_bot.services.projects import list_user_active_projects

_NO_PROJECTS_TEXT = (
    "Вы пока не состоите ни в одном проекте. Зарегистрируйтесь по ссылке из поста "
    "регистрации в вашем групповом чате."
)
_NO_EVENTS_TEXT = (
    "Нет мероприятий, которые вы можете отменить. Отмена доступна организаторам "
    "мероприятия, а если организатор не назначен — создателю и админам проекта."
)
_PICK_EVENT_TEXT = "Какое мероприятие отменить?"
_CONFIRM_TEXT = "Отменить мероприятие «{label}»? Подтвердившим участие уйдёт уведомление."
_STALE_TEXT = "Мероприятие уже нельзя отменить — оно отменено, прошло или удалено."
_NO_ACCESS_TEXT = (
    "Нет прав на отмену этого мероприятия. Отменить может организатор, а если "
    "организатор не назначен — создатель и админы проекта."
)
_CANCELLED_HEAD = "Мероприятие отменено."
_ANNOUNCEMENT_OK = "Анонс в чате помечен «отменено», RSVP-кнопки убраны."
_ANNOUNCEMENT_FAILED = (
    "⚠️ Анонс в чате обновить не удалось — пометьте отмену и уберите кнопки "
    "вручную либо проверьте, что бот всё ещё может редактировать то сообщение."
)
_NOTIFIED = "Подтвердившим участие ушло уведомление: {count}."
_ABORTED_TEXT = "Отмена мероприятия не выполнена."


def _result_text(*, notified: int, announcement_ok: bool) -> str:
    lines = [_CANCELLED_HEAD]
    if notified:
        lines.append(_NOTIFIED.format(count=notified))
    lines.append(_ANNOUNCEMENT_OK if announcement_ok else _ANNOUNCEMENT_FAILED)
    return "\n".join(lines)

_PICK_PREFIX = "cev"
_CONFIRM_PREFIX = "cec"
_ABORT_DATA = "cex"

_BUTTON_TEXT_LIMIT = 64


def _event_button_label(event: Event, timezone: str) -> str:
    head = event.title or event.location
    label = f"{format_short_datetime(event.starts_at, timezone)} · {head}"
    if len(label) > _BUTTON_TEXT_LIMIT:
        label = label[: _BUTTON_TEXT_LIMIT - 1] + "…"
    return label


async def _project_timezone(session: AsyncSession, project_id: int) -> str:
    settings = await session.get(ProjectSettings, project_id)
    return settings.timezone if settings is not None else DEFAULT_TIMEZONE


async def _load_cancelable_event(
    session: AsyncSession, *, tg_user_id: int, event_id: int
) -> tuple[Event | None, str]:
    """`(event, "")`, если `tg_user_id` вправе отменить мероприятие прямо сейчас,
    иначе `(None, текст ошибки)`. Повторяется на каждом шаге callback-цепочки:
    `callback_data` подделывается вручную."""
    event = await session.get(Event, event_id)
    if (
        event is None
        or event.status != EventStatus.PLANNED
        or event.attendance_finalized_at is not None
    ):
        return None, _STALE_TEXT
    user_id = await resolve_member_user_id(
        session, project_id=event.project_id, tg_user_id=tg_user_id
    )
    if user_id is None:
        return None, _NO_ACCESS_TEXT
    is_admin = await user_is_project_admin(
        session, project_id=event.project_id, user_id=user_id
    )
    if not await can_manage_event(
        session, event=event, user_id=user_id, is_admin=is_admin
    ):
        return None, _NO_ACCESS_TEXT
    return event, ""


def create_router() -> Router:
    router = Router(name="cancel_event")

    @router.message(Command("cancel_event"), F.chat.type == "private")
    async def on_cancel_event(message: Message, session: AsyncSession) -> None:
        if message.from_user is None:
            return

        projects = await list_user_active_projects(
            session, tg_user_id=message.from_user.id
        )
        if not projects:
            await message.answer(_NO_PROJECTS_TEXT)
            return

        buttons: list[list[InlineKeyboardButton]] = []
        for project in projects:
            user_id = await resolve_member_user_id(
                session, project_id=project.id, tg_user_id=message.from_user.id
            )
            if user_id is None:
                continue
            is_admin = await user_is_project_admin(
                session, project_id=project.id, user_id=user_id
            )
            events = await list_manageable_events(
                session, project_id=project.id, user_id=user_id, is_admin=is_admin
            )
            if not events:
                continue
            timezone = await _project_timezone(session, project.id)
            for event in events:
                buttons.append(
                    [
                        InlineKeyboardButton(
                            text=_event_button_label(event, timezone),
                            callback_data=f"{_PICK_PREFIX}:{event.id}",
                        )
                    ]
                )

        if not buttons:
            await message.answer(_NO_EVENTS_TEXT)
            return

        await message.answer(
            _PICK_EVENT_TEXT,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )

    @router.callback_query(F.data.startswith(f"{_PICK_PREFIX}:"))
    async def on_pick(callback: CallbackQuery, session: AsyncSession) -> None:
        if callback.data is None or callback.message is None or callback.from_user is None:
            return

        event_id = int(callback.data.split(":", 1)[1])
        event, error = await _load_cancelable_event(
            session, tg_user_id=callback.from_user.id, event_id=event_id
        )
        if event is None:
            await callback.answer(error, show_alert=True)
            return

        timezone = await _project_timezone(session, event.project_id)
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🚫 Да, отменить",
                        callback_data=f"{_CONFIRM_PREFIX}:{event.id}",
                    ),
                    InlineKeyboardButton(text="Назад", callback_data=_ABORT_DATA),
                ]
            ]
        )
        await callback.message.edit_text(  # type: ignore[union-attr]
            _CONFIRM_TEXT.format(label=_event_button_label(event, timezone)),
            reply_markup=keyboard,
        )
        await callback.answer()

    @router.callback_query(F.data.startswith(f"{_CONFIRM_PREFIX}:"))
    async def on_confirm(
        callback: CallbackQuery, session: AsyncSession, bot: Bot
    ) -> None:
        if callback.data is None or callback.message is None or callback.from_user is None:
            return

        event_id = int(callback.data.split(":", 1)[1])
        event, error = await _load_cancelable_event(
            session, tg_user_id=callback.from_user.id, event_id=event_id
        )
        if event is None:
            await callback.answer(error, show_alert=True)
            return

        timezone = await _project_timezone(session, event.project_id)
        event.status = EventStatus.CANCELLED
        await session.flush()
        # Неправимый анонс (сообщение удалили, бот потерял права, публикации не
        # было) не должен мешать отмене — она уже применена в БД; о неудаче
        # сообщаем вызвавшему отдельной строкой.
        try:
            announcement_ok = await refresh_event_announcement(bot, session, event)
        except TelegramAPIError:
            announcement_ok = False
        await session.commit()

        notified = await notify_going_members(
            bot,
            session,
            event,
            text=build_event_cancelled_notification(event, timezone=timezone),
        )
        await callback.message.edit_text(  # type: ignore[union-attr]
            _result_text(notified=notified, announcement_ok=announcement_ok)
        )
        await callback.answer()

    @router.callback_query(F.data == _ABORT_DATA)
    async def on_abort(callback: CallbackQuery) -> None:
        if callback.message is not None:
            await callback.message.edit_text(_ABORTED_TEXT)  # type: ignore[union-attr]
        await callback.answer()

    return router
