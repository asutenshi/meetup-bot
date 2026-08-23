from aiogram import Bot, F, Router
from aiogram.types import ChatMemberUpdated
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.services.projects import provision_project

_LEFT_STATUSES = {"left", "kicked"}
_JOINED_STATUSES = {"member", "administrator"}


def create_router() -> Router:
    router = Router(name="chat_member")

    @router.my_chat_member(F.chat.type.in_({"group", "supergroup"}))
    async def on_bot_membership_changed(
        event: ChatMemberUpdated, session: AsyncSession, bot: Bot
    ) -> None:
        if event.new_chat_member.user.id != bot.id:
            return
        if event.old_chat_member.status not in _LEFT_STATUSES:
            return
        if event.new_chat_member.status not in _JOINED_STATUSES:
            return

        await provision_project(
            session,
            tg_chat_id=event.chat.id,
            chat_name=event.chat.title or str(event.chat.id),
            thread_id=None,
            force_thread_id=False,
            admin_tg_user_id=event.from_user.id,
            admin_username=event.from_user.username,
            admin_first_name=event.from_user.first_name,
            admin_last_name=event.from_user.last_name,
        )
        await session.commit()

    return router
