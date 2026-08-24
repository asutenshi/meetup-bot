from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.enums import MembershipRole
from meetup_bot.db.models import Project
from meetup_bot.services.projects import ensure_membership, get_or_create_user

_NO_PAYLOAD_TEXT = (
    "Чтобы зарегистрироваться в проекте, перейдите по ссылке из поста "
    "регистрации в вашем групповом чате."
)
_UNKNOWN_PAYLOAD_TEXT = (
    "Ссылка регистрации недействительна. Перейдите по ссылке из поста "
    "регистрации в вашем групповом чате."
)
_WELCOME_TEXT = (
    "Вы зарегистрированы в проекте «{project_name}»! Теперь вам будут "
    "приходить сюда личные напоминания от бота."
)


def create_router() -> Router:
    router = Router(name="start")

    @router.message(CommandStart(), F.chat.type == "private")
    async def on_start(
        message: Message, command: CommandObject, session: AsyncSession
    ) -> None:
        if message.from_user is None:
            return

        payload = command.args
        if not payload:
            await message.answer(_NO_PAYLOAD_TEXT)
            return

        project = await session.scalar(
            select(Project).where(Project.invite_payload == payload)
        )
        if project is None:
            await message.answer(_UNKNOWN_PAYLOAD_TEXT)
            return

        user = await get_or_create_user(
            session,
            tg_user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        await ensure_membership(
            session, project_id=project.id, user_id=user.id, role=MembershipRole.MEMBER
        )
        await session.commit()

        await message.answer(_WELCOME_TEXT.format(project_name=project.name))

    return router
