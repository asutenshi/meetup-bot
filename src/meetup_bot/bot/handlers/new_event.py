"""`/new_event` — точка входа в форму создания мероприятия (Mini App).

Только в приватном чате с ботом (`F.chat.type == "private"`, как `/start`): все
точки входа в Mini App — из лички (TZ §3.8). Бот отвечает сообщением с
`InlineKeyboardButton(web_app=…)`, ведущей на форму в контексте проекта. Если
участник состоит в нескольких проектах — сперва инлайн-выбор проекта, затем
кнопка с уже подставленным контекстом.

Сама форма и `POST /api/events` — задача 2.5; здесь только кнопка и выбор проекта.
"""

from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.config import Settings
from meetup_bot.db.models import Project
from meetup_bot.services.projects import is_active_member, list_user_active_projects
from meetup_bot.services.webapp_url import build_web_app_url

_NOT_CONFIGURED_TEXT = (
    "Создание мероприятий пока недоступно: не настроен публичный адрес Web App. "
    "Обратитесь к администратору бота."
)
_NO_PROJECTS_TEXT = (
    "Вы пока не состоите ни в одном проекте. Зарегистрируйтесь по ссылке из поста "
    "регистрации в вашем групповом чате."
)
_PICK_PROJECT_TEXT = "Для какого проекта создать мероприятие?"
_OPEN_FORM_TEXT = "Создание мероприятия для проекта «{project_name}»."
_BUTTON_TEXT = "Создать мероприятие"
_STALE_ACTION_TEXT = "Проект больше недоступен — вызовите /new_event заново."

_PICK_PREFIX = "nev"

_MAX_BUTTON_TEXT_LENGTH = 64


def _button_label(project: Project) -> str:
    if len(project.name) > _MAX_BUTTON_TEXT_LENGTH:
        return project.name[: _MAX_BUTTON_TEXT_LENGTH - 1] + "…"
    return project.name


def _open_form_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=_BUTTON_TEXT, web_app=WebAppInfo(url=url))]]
    )


def create_router() -> Router:
    router = Router(name="new_event")

    @router.message(Command("new_event"), F.chat.type == "private")
    async def on_new_event(
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

        if len(projects) == 1:
            project = projects[0]
            url = build_web_app_url(
                settings.public_base_url, project_payload=project.invite_payload
            )
            await message.answer(
                _OPEN_FORM_TEXT.format(project_name=escape(project.name)),
                reply_markup=_open_form_keyboard(url),
            )
            return

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_button_label(project),
                        callback_data=f"{_PICK_PREFIX}:{project.id}",
                    )
                ]
                for project in projects
            ]
        )
        await message.answer(_PICK_PROJECT_TEXT, reply_markup=keyboard)

    @router.callback_query(F.data.startswith(f"{_PICK_PREFIX}:"))
    async def on_pick_project(
        callback: CallbackQuery, session: AsyncSession, settings: Settings | None
    ) -> None:
        if callback.data is None or callback.message is None or callback.from_user is None:
            return
        if settings is None or not settings.public_base_url:
            await callback.answer(_NOT_CONFIGURED_TEXT, show_alert=True)
            return

        project_id = int(callback.data.split(":", 1)[1])
        project = await session.get(Project, project_id)
        # Членство сверяем заново: список мог устареть (участника удалили, проект
        # деактивировали), а callback_data подделывается вручную.
        if (
            project is None
            or not project.is_active
            or not await is_active_member(
                session, project_id=project.id, tg_user_id=callback.from_user.id
            )
        ):
            await callback.answer(_STALE_ACTION_TEXT, show_alert=True)
            return

        url = build_web_app_url(
            settings.public_base_url, project_payload=project.invite_payload
        )
        await callback.message.edit_text(  # type: ignore[union-attr]
            _OPEN_FORM_TEXT.format(project_name=escape(project.name)),
            reply_markup=_open_form_keyboard(url),
        )
        await callback.answer()

    return router
