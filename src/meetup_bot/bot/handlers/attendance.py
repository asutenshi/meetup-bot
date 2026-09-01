"""`/attendance` — точка входа в экран постфактум-корректировки RSVP (Mini App).

Только в приватном чате с ботом (как `/edit_event`, `/cancel_event`): все точки
входа в Mini App — из лички (TZ §3.8). Бот присылает список мероприятий, чей RSVP
вызвавший вправе править (то же правило `can_manage_event`, что у
редактирования), кроме отменённых и включая уже финализированные — у каждого
`web_app`-кнопка с контекстом проекта и `attendance=<event_id>`. Право
проверяется повторно на бэкенде (`/api/events/{id}/attendance`).
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.config import Settings
from meetup_bot.db.models import Event, ProjectSettings
from meetup_bot.services.event_announcement import DEFAULT_TIMEZONE, format_short_datetime
from meetup_bot.services.events import (
    list_events_for_rsvp_correction,
    resolve_member_user_id,
    user_is_project_admin,
)
from meetup_bot.services.projects import list_user_active_projects
from meetup_bot.services.webapp_url import build_web_app_url

_NOT_CONFIGURED_TEXT = (
    "Корректировка явки пока недоступна: не настроен публичный адрес Web App. "
    "Обратитесь к администратору бота."
)
_NO_PROJECTS_TEXT = (
    "Вы пока не состоите ни в одном проекте. Зарегистрируйтесь по ссылке из поста "
    "регистрации в вашем групповом чате."
)
_NO_EVENTS_TEXT = (
    "Нет мероприятий, у которых вы можете править явку. Экран доступен организаторам "
    "мероприятия, а если организатор не назначен — создателю и админам проекта."
)
_PICK_EVENT_TEXT = "У какого мероприятия поправить явку?"
_BUTTON_TEXT_LIMIT = 64


def _event_button_label(event: Event, timezone: str) -> str:
    head = event.title or event.location
    label = f"{format_short_datetime(event.starts_at, timezone)} · {head}"
    if len(label) > _BUTTON_TEXT_LIMIT:
        label = label[: _BUTTON_TEXT_LIMIT - 1] + "…"
    return label


def create_router() -> Router:
    router = Router(name="attendance")

    @router.message(Command("attendance"), F.chat.type == "private")
    async def on_attendance(
        message: Message, session: AsyncSession, settings: Settings | None
    ) -> None:
        if message.from_user is None:
            return
        if settings is None or not settings.public_base_url:
            await message.answer(_NOT_CONFIGURED_TEXT)
            return

        projects = await list_user_active_projects(session, tg_user_id=message.from_user.id)
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
            events = await list_events_for_rsvp_correction(
                session, project_id=project.id, user_id=user_id, is_admin=is_admin
            )
            if not events:
                continue
            project_settings = await session.get(ProjectSettings, project.id)
            timezone = (
                project_settings.timezone
                if project_settings is not None
                else DEFAULT_TIMEZONE
            )
            for event in events:
                url = build_web_app_url(
                    settings.public_base_url,
                    project_payload=project.invite_payload,
                    attendance_event_id=event.id,
                )
                buttons.append(
                    [
                        InlineKeyboardButton(
                            text=_event_button_label(event, timezone),
                            web_app=WebAppInfo(url=url),
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

    return router
