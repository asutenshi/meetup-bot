from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.services.projects import provision_project

_CONFIRMATION_WITH_TOPIC = (
    "Готово! Этот топик назначен топиком по умолчанию для сообщений бота."
)
_CONFIRMATION_WITHOUT_TOPIC = (
    "Готово! Сообщения бота по умолчанию будут приходить в общий чат "
    "(без привязки к топику)."
)


def create_router() -> Router:
    router = Router(name="setup_registration")

    @router.message(Command("setup_registration"), F.chat.type.in_({"group", "supergroup"}))
    async def on_setup_registration(message: Message, session: AsyncSession) -> None:
        if message.from_user is None:
            return

        await provision_project(
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
        await session.commit()

        text = (
            _CONFIRMATION_WITH_TOPIC
            if message.message_thread_id is not None
            else _CONFIRMATION_WITHOUT_TOPIC
        )
        await message.answer(text)

    return router
