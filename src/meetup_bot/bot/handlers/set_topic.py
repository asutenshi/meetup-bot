from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.enums import TopicCategory
from meetup_bot.db.models import Project
from meetup_bot.services.projects import (
    is_project_admin,
    set_project_topic,
    unset_project_topic,
)

_NOT_SET_UP_TEXT = (
    "Бот ещё не настроен в этом чате. Администратор должен вызвать "
    "/setup_registration."
)
_NOT_ADMIN_TEXT = "Эту команду может вызвать только администратор проекта."
_NOT_FORUM_TEXT = "В этом чате нет топиков — привязка топика к категории не нужна."
_OUTSIDE_TOPIC_TEXT = (
    "Вызовите эту команду внутри топика, который должен принимать сообщения "
    "выбранной категории."
)
_INVALID_CATEGORY_TEXT = (
    "Укажите категорию после команды, например: /set_topic events. Доступные "
    "категории: " + ", ".join(category.value for category in TopicCategory) + "."
)
_CONFIRMATION_TEXT = {
    TopicCategory.EVENTS: "Готово! Мероприятия теперь будут анонсироваться в этом топике.",
    TopicCategory.MONEY_COLLECTIONS: (
        "Готово! Уведомления о сборах теперь будут приходить в этот топик."
    ),
    TopicCategory.GENERAL: "Готово! Остальные сообщения бота теперь будут приходить в этот топик.",
    TopicCategory.RIGHTS: (
        "Готово! Admin-команды регулирования прав теперь можно вызывать только из этого топика."
    ),
}
_ALREADY_ASSIGNED_TEXT = {
    TopicCategory.EVENTS: "Этот топик уже назначен для анонсов мероприятий.",
    TopicCategory.MONEY_COLLECTIONS: "Этот топик уже назначен для уведомлений о сборах.",
    TopicCategory.GENERAL: "Этот топик уже назначен для остальных сообщений бота.",
    TopicCategory.RIGHTS: "Этот топик уже назначен топиком регулирования прав.",
}
_UNSET_CONFIRMATION_TEXT = {
    TopicCategory.EVENTS: (
        "Готово! Анонсы мероприятий больше не привязаны к отдельному топику — "
        "уходят в топик по умолчанию."
    ),
    TopicCategory.MONEY_COLLECTIONS: (
        "Готово! Уведомления о сборах больше не привязаны к отдельному топику — "
        "уходят в топик по умолчанию."
    ),
    TopicCategory.GENERAL: (
        "Готово! Прочие сообщения бота больше не привязаны к отдельному топику — "
        "уходят в топик по умолчанию."
    ),
    TopicCategory.RIGHTS: (
        "Готово! Топик регулирования прав снят — admin-команды снова можно "
        "вызывать из любого топика."
    ),
}
_UNSET_NOT_ASSIGNED_TEXT = "Для этой категории топик и так не был назначен."


def create_router() -> Router:
    router = Router(name="set_topic")

    @router.message(Command("set_topic"), F.chat.type.in_({"group", "supergroup"}))
    async def on_set_topic(
        message: Message, command: CommandObject, session: AsyncSession
    ) -> None:
        if message.from_user is None:
            return

        # Проверки прав раньше разбора аргументов (TZ §3.5): иначе не-админ,
        # вызвавший команду без категории, получает список категорий и видит
        # отказ по правам только после того, как подставит корректную.
        project = await session.scalar(
            select(Project).where(Project.tg_chat_id == message.chat.id)
        )
        if project is None:
            await message.answer(_NOT_SET_UP_TEXT)
            return

        if not await is_project_admin(
            session, project_id=project.id, tg_user_id=message.from_user.id
        ):
            await message.answer(_NOT_ADMIN_TEXT)
            return

        raw_category = (command.args or "").strip()
        try:
            category = TopicCategory(raw_category)
        except ValueError:
            await message.answer(_INVALID_CATEGORY_TEXT)
            return

        if not message.chat.is_forum:
            await message.answer(_NOT_FORUM_TEXT)
            return

        if message.message_thread_id is None:
            await message.answer(_OUTSIDE_TOPIC_TEXT)
            return

        _setting, changed = await set_project_topic(
            session,
            project_id=project.id,
            category=category,
            thread_id=message.message_thread_id,
        )
        if not changed:
            await message.answer(_ALREADY_ASSIGNED_TEXT[category])
            return

        await session.commit()
        await message.answer(_CONFIRMATION_TEXT[category])

    @router.message(Command("unset_topic"), F.chat.type.in_({"group", "supergroup"}))
    async def on_unset_topic(
        message: Message, command: CommandObject, session: AsyncSession
    ) -> None:
        if message.from_user is None:
            return

        # Тот же порядок проверок, что и у `/set_topic`: проект и роль раньше
        # аргументов. `/unset_topic` не привязана к конкретному топику (TZ §3.5)
        # и не входит в гейт прав (TZ §3.7) — вызывается откуда угодно.
        project = await session.scalar(
            select(Project).where(Project.tg_chat_id == message.chat.id)
        )
        if project is None:
            await message.answer(_NOT_SET_UP_TEXT)
            return

        if not await is_project_admin(
            session, project_id=project.id, tg_user_id=message.from_user.id
        ):
            await message.answer(_NOT_ADMIN_TEXT)
            return

        raw_category = (command.args or "").strip()
        try:
            category = TopicCategory(raw_category)
        except ValueError:
            await message.answer(_INVALID_CATEGORY_TEXT)
            return

        removed = await unset_project_topic(session, project_id=project.id, category=category)
        if not removed:
            await message.answer(_UNSET_NOT_ASSIGNED_TEXT)
            return

        await session.commit()
        await message.answer(_UNSET_CONFIRMATION_TEXT[category])

    return router
