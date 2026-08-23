from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.types import Update
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.bot import create_dispatcher
from meetup_bot.db.enums import MembershipRole
from meetup_bot.db.models import Project, ProjectMembership, User

BOT_TOKEN = "123:test-token"


@pytest.fixture
def bot(monkeypatch: pytest.MonkeyPatch) -> Bot:
    """Бот с заглушенным вызовом Telegram Bot API — хендлер отвечает сообщением
    в чат, но тест не должен делать реальные сетевые запросы."""
    monkeypatch.setattr(Bot, "__call__", AsyncMock(return_value=None))
    return Bot(token=BOT_TOKEN)


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
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dispatcher = create_dispatcher(session_factory)
    update = Update.model_validate(_setup_registration_update(message_thread_id=7))

    await dispatcher.feed_update(bot=bot, update=update)

    async with session_factory() as session:
        project = await session.scalar(select(Project).where(Project.tg_chat_id == -100123))
        assert project is not None
        assert project.default_thread_id == 7

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
