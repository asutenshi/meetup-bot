from aiogram import Bot, F, Router
from aiogram.types import ChatMemberUpdated
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.services.projects import provision_project
from meetup_bot.services.registration_post import sync_registration_post
from meetup_bot.services.users import clear_bot_blocked, mark_bot_blocked

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

        project, created, thread_changed = await provision_project(
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
        if created or thread_changed:
            await sync_registration_post(bot, project)
        await session.commit()

    @router.my_chat_member(F.chat.type == "private")
    async def on_private_membership_changed(
        event: ChatMemberUpdated, session: AsyncSession, bot: Bot
    ) -> None:
        """Блокировка/разблокировка бота в личке (TZ §6.2, задача 5.1).

        Telegram шлёт `my_chat_member` со сменой статуса самого бота: `kicked` —
        человек заблокировал, `member` — разблокировал. Помечаем `User`, чтобы
        worker не долбил заблокировавшего личными напоминаниями."""
        if event.new_chat_member.user.id != bot.id:
            return
        if event.new_chat_member.status == "kicked":
            await mark_bot_blocked(session, tg_user_id=event.from_user.id)
        elif event.new_chat_member.status == "member":
            await clear_bot_blocked(session, tg_user_id=event.from_user.id)
        else:
            return
        await session.commit()

    return router
