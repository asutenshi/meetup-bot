from aiogram import Bot, F, Router
from aiogram.types import ChatMemberUpdated
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.enums import MembershipRole
from meetup_bot.services.projects import (
    ensure_membership,
    get_or_create_project,
    get_or_create_user,
)

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

        project, _ = await get_or_create_project(
            session, tg_chat_id=event.chat.id, name=event.chat.title or str(event.chat.id)
        )
        user = await get_or_create_user(
            session,
            tg_user_id=event.from_user.id,
            username=event.from_user.username,
            first_name=event.from_user.first_name,
            last_name=event.from_user.last_name,
        )
        await ensure_membership(
            session, project_id=project.id, user_id=user.id, role=MembershipRole.ADMIN
        )
        await session.commit()

    return router
