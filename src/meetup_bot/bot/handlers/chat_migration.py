from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.services.projects import migrate_project_chat_id


def create_router() -> Router:
    router = Router(name="chat_migration")

    @router.message(F.migrate_to_chat_id.is_not(None) | F.migrate_from_chat_id.is_not(None))
    async def on_chat_migrated(message: Message, session: AsyncSession) -> None:
        """При повышении обычной группы до супергруппы Telegram меняет `chat.id` и
        присылает служебное сообщение: с `migrate_to_chat_id` в старой группе и с
        `migrate_from_chat_id` в новой супергруппе. Оба ведут сюда — переносим
        проект на новый `tg_chat_id`, чтобы бот не завёл дубль (TZ §3.3)."""
        if message.migrate_to_chat_id is not None:
            old_chat_id, new_chat_id = message.chat.id, message.migrate_to_chat_id
        elif message.migrate_from_chat_id is not None:
            old_chat_id, new_chat_id = message.migrate_from_chat_id, message.chat.id
        else:  # pragma: no cover - фильтр роутера это исключает
            return

        changed = await migrate_project_chat_id(
            session, old_chat_id=old_chat_id, new_chat_id=new_chat_id
        )
        if changed:
            await session.commit()

    return router
