from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.models import Project
from meetup_bot.services.projects import is_project_admin, provision_project
from meetup_bot.services.registration_post import sync_registration_post

_CONFIRMATION_WITH_TOPIC = (
    "Готово! Этот топик назначен топиком по умолчанию для сообщений бота."
)
_CONFIRMATION_WITHOUT_TOPIC = (
    "Готово! Сообщения бота по умолчанию будут приходить в общий чат "
    "(без привязки к топику)."
)
_NOT_ADMIN_TEXT = "Эту команду может вызвать только администратор проекта."


def create_router() -> Router:
    router = Router(name="setup_registration")

    @router.message(Command("setup_registration"), F.chat.type.in_({"group", "supergroup"}))
    async def on_setup_registration(message: Message, session: AsyncSession, bot: Bot) -> None:
        if message.from_user is None:
            return

        # Проект уже мог существовать — тогда менять его топик и переиздавать
        # пост регистрации может только уже назначенный админ (TZ §6.1 "права
        # ролей"), иначе любой участник чата смог бы вызвать команду и стать
        # со-админом через `provision_project`. Если проекта ещё нет, первый
        # вызов создаёт его и назначает вызвавшего первым админом (TZ §3.3,
        # шаг 2) — проверка тут не нужна.
        existing_project = await session.scalar(
            select(Project).where(Project.tg_chat_id == message.chat.id)
        )
        if existing_project is not None and not await is_project_admin(
            session, project_id=existing_project.id, tg_user_id=message.from_user.id
        ):
            await message.answer(_NOT_ADMIN_TEXT)
            return

        project, created, thread_changed = await provision_project(
            session,
            tg_chat_id=message.chat.id,
            chat_name=message.chat.title or str(message.chat.id),
            thread_id=message.message_thread_id,
            force_thread_id=True,
            admin_tg_user_id=message.from_user.id,
            admin_username=message.from_user.username,
            admin_first_name=message.from_user.first_name,
            admin_last_name=message.from_user.last_name,
        )
        if created or thread_changed:
            await sync_registration_post(bot, project)
        await session.commit()

        text = (
            _CONFIRMATION_WITH_TOPIC
            if message.message_thread_id is not None
            else _CONFIRMATION_WITHOUT_TOPIC
        )
        await message.answer(text)

    return router
