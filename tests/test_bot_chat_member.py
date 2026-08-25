from aiogram import Bot
from aiogram.types import Update
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.bot import create_dispatcher
from meetup_bot.db.enums import MembershipRole
from meetup_bot.db.models import Project, ProjectMembership, User
from tests.conftest import FakeBotApi


def _bot_added_update(update_id: int = 1, chat_id: int = -100123, old_status: str = "left") -> dict:
    return {
        "update_id": update_id,
        "my_chat_member": {
            "chat": {"id": chat_id, "type": "supergroup", "title": "Test Group"},
            "from": {
                "id": 555,
                "is_bot": False,
                "first_name": "Admin",
                "username": "admin_user",
            },
            "date": 1700000000,
            "old_chat_member": {
                "user": {"id": 123, "is_bot": True, "first_name": "TestBot"},
                "status": old_status,
            },
            "new_chat_member": {
                "user": {"id": 123, "is_bot": True, "first_name": "TestBot"},
                "status": "member",
            },
        },
    }


async def test_bot_added_to_group_creates_project_and_admin(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dispatcher = create_dispatcher(session_factory)
    update = Update.model_validate(_bot_added_update())

    await dispatcher.feed_update(bot=bot, update=update)

    async with session_factory() as session:
        project = await session.scalar(select(Project).where(Project.tg_chat_id == -100123))
        assert project is not None
        assert project.name == "Test Group"
        assert project.pinned_message_id is not None
        assert fake_bot_api.posts == [project.pinned_message_id]

        user = await session.scalar(select(User).where(User.tg_user_id == 555))
        assert user is not None

        membership = await session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project.id,
                ProjectMembership.user_id == user.id,
            )
        )
        assert membership is not None
        assert membership.role == MembershipRole.OWNER


async def test_repeated_add_event_is_idempotent(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_bot_added_update(1)))
    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_bot_added_update(2)))

    async with session_factory() as session:
        projects = (
            await session.scalars(select(Project).where(Project.tg_chat_id == -100123))
        ).all()
        memberships = (await session.scalars(select(ProjectMembership))).all()

    assert len(projects) == 1
    assert len(memberships) == 1
    # Повторное добавление бота (тот же топик, ещё не заданный) не должно
    # публиковать второй пост регистрации поверх уже существующего.
    assert len(fake_bot_api.posts) == 1


async def test_status_change_other_than_join_is_ignored(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dispatcher = create_dispatcher(session_factory)
    update = Update.model_validate(_bot_added_update(old_status="member"))

    await dispatcher.feed_update(bot=bot, update=update)

    async with session_factory() as session:
        project = await session.scalar(select(Project).where(Project.tg_chat_id == -100123))

    assert project is None
    assert fake_bot_api.posts == []
