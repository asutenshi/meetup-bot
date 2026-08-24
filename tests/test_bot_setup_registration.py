from aiogram import Bot
from aiogram.types import Update
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.bot import create_dispatcher
from meetup_bot.db.enums import MembershipRole
from meetup_bot.db.models import Project, ProjectMembership, User
from tests.conftest import FakeBotApi


def _setup_registration_update(
    update_id: int = 1,
    chat_id: int = -100123,
    user_id: int = 555,
    message_thread_id: int | None = None,
) -> dict:
    message: dict = {
        "message_id": update_id,
        "date": 1700000000,
        "chat": {"id": chat_id, "type": "supergroup", "title": "Test Group"},
        "from": {
            "id": user_id,
            "is_bot": False,
            "first_name": "Admin",
            "username": "admin_user",
        },
        "text": "/setup_registration",
        "entities": [{"type": "bot_command", "offset": 0, "length": 20}],
    }
    if message_thread_id is not None:
        message["message_thread_id"] = message_thread_id
        message["is_topic_message"] = True
    return {"update_id": update_id, "message": message}


async def test_setup_registration_creates_project_and_admin(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dispatcher = create_dispatcher(session_factory)
    update = Update.model_validate(_setup_registration_update(message_thread_id=7))

    await dispatcher.feed_update(bot=bot, update=update)

    async with session_factory() as session:
        project = await session.scalar(select(Project).where(Project.tg_chat_id == -100123))
        assert project is not None
        assert project.default_thread_id == 7
        assert project.pinned_message_id is not None
        assert fake_bot_api.posts == [project.pinned_message_id]
        # Бот не закрепляет пост сам — только напоминает об этом администратору.
        assert any("Закрепите" in text for text in fake_bot_api.sent_texts)

        user = await session.scalar(select(User).where(User.tg_user_id == 555))
        assert user is not None

        membership = await session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project.id,
                ProjectMembership.user_id == user.id,
            )
        )
        assert membership is not None
        assert membership.role == MembershipRole.ADMIN


async def test_setup_registration_without_topic_leaves_default_thread_null(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dispatcher = create_dispatcher(session_factory)
    update = Update.model_validate(_setup_registration_update())

    await dispatcher.feed_update(bot=bot, update=update)

    async with session_factory() as session:
        project = await session.scalar(select(Project).where(Project.tg_chat_id == -100123))

    assert project is not None
    assert project.default_thread_id is None


async def test_repeated_call_in_another_topic_updates_default_thread(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_setup_registration_update(1, message_thread_id=7))
    )
    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_setup_registration_update(2, message_thread_id=9))
    )

    async with session_factory() as session:
        projects = (
            await session.scalars(select(Project).where(Project.tg_chat_id == -100123))
        ).all()
        memberships = (await session.scalars(select(ProjectMembership))).all()

    assert len(projects) == 1
    assert projects[0].default_thread_id == 9
    assert len(memberships) == 1
    # Пост перенесён в новый топик: публикуется заново (TZ §3.3, шаг 3), старый
    # пост бот не трогает — закрепление и открепление на ответственности админа.
    assert len(fake_bot_api.posts) == 2
    assert projects[0].pinned_message_id == fake_bot_api.posts[1]


async def test_repeated_call_in_same_topic_does_not_republish(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_setup_registration_update(1, message_thread_id=7))
    )
    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_setup_registration_update(2, message_thread_id=7))
    )

    async with session_factory() as session:
        project = await session.scalar(select(Project).where(Project.tg_chat_id == -100123))

    assert project is not None
    assert len(fake_bot_api.posts) == 1
    assert project.pinned_message_id == fake_bot_api.posts[0]
