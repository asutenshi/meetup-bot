from aiogram import Bot
from aiogram.types import Update
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.bot import create_dispatcher
from meetup_bot.db.models import Project
from meetup_bot.services.projects import get_or_create_project
from tests.conftest import FakeBotApi

_OLD_CHAT_ID = -5540338868
_NEW_CHAT_ID = -1003796522778


def _migrate_from_update(update_id: int = 1) -> dict:
    """Служебное сообщение в новой супергруппе: `chat.id` уже новый, старый —
    в `migrate_from_chat_id`."""
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "date": 1700000000,
            "chat": {"id": _NEW_CHAT_ID, "type": "supergroup", "title": "Test Group"},
            "migrate_from_chat_id": _OLD_CHAT_ID,
        },
    }


def _migrate_to_update(update_id: int = 1) -> dict:
    """Служебное сообщение в старой группе: `chat.id` ещё старый, новый —
    в `migrate_to_chat_id`."""
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "date": 1700000000,
            "chat": {"id": _OLD_CHAT_ID, "type": "group", "title": "Test Group"},
            "migrate_to_chat_id": _NEW_CHAT_ID,
        },
    }


async def _seed_project(
    session_factory: async_sessionmaker[AsyncSession], tg_chat_id: int
) -> str:
    async with session_factory() as session:
        project, _ = await get_or_create_project(
            session, tg_chat_id=tg_chat_id, name="Test Group"
        )
        await session.commit()
        return project.invite_payload


async def test_migrate_from_chat_id_repoints_project(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    payload = await _seed_project(session_factory, _OLD_CHAT_ID)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_migrate_from_update()))

    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Project)) == 1
        project = await session.scalar(
            select(Project).where(Project.tg_chat_id == _NEW_CHAT_ID)
        )
        assert project is not None
        assert project.invite_payload == payload


async def test_migrate_to_chat_id_repoints_project(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_project(session_factory, _OLD_CHAT_ID)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_migrate_to_update()))

    async with session_factory() as session:
        project = await session.scalar(
            select(Project).where(Project.tg_chat_id == _NEW_CHAT_ID)
        )
        assert project is not None


async def test_both_migration_messages_are_idempotent(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_project(session_factory, _OLD_CHAT_ID)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_migrate_from_update(1)))
    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_migrate_to_update(2)))

    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Project)) == 1


async def test_migration_message_for_unknown_group_is_noop(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_migrate_from_update()))

    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Project)) == 0
