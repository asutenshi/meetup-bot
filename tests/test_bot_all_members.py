from aiogram import Bot
from aiogram.types import Update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.bot import create_dispatcher
from meetup_bot.db.enums import MembershipRole, MembershipStatus
from meetup_bot.db.models import Project, ProjectMembership, ProjectSettings, User
from tests.conftest import FakeBotApi

_CHAT_ID = -100777


def _all_update(
    update_id: int = 1,
    chat_id: int = _CHAT_ID,
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
            "first_name": "Caller",
            "username": "caller_user",
        },
        "text": "/all",
        "entities": [{"type": "bot_command", "offset": 0, "length": 4}],
    }
    if message_thread_id is not None:
        message["message_thread_id"] = message_thread_id
        message["is_topic_message"] = True
    return {"update_id": update_id, "message": message}


async def _create_project(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    chat_id: int = _CHAT_ID,
    all_command_throttle_seconds: int = 180,
) -> Project:
    async with session_factory() as session:
        project = Project(
            tg_chat_id=chat_id,
            name="Test Group",
            invite_payload=f"payload-{chat_id}",
        )
        session.add(project)
        await session.flush()
        session.add(
            ProjectSettings(
                project_id=project.id,
                all_command_throttle_seconds=all_command_throttle_seconds,
            )
        )
        await session.commit()
        await session.refresh(project)
        return project


async def _add_member(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: int,
    *,
    tg_user_id: int,
    username: str | None,
    first_name: str = "Member",
    status: MembershipStatus = MembershipStatus.ACTIVE,
) -> None:
    async with session_factory() as session:
        user = User(tg_user_id=tg_user_id, username=username, first_name=first_name)
        session.add(user)
        await session.flush()
        session.add(
            ProjectMembership(
                project_id=project_id,
                user_id=user.id,
                role=MembershipRole.MEMBER,
                status=status,
            )
        )
        await session.commit()


async def test_all_mentions_active_members_outside_topic(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(session_factory, project.id, tg_user_id=1, username="alice")
    await _add_member(session_factory, project.id, tg_user_id=2, username=None, first_name="Bob")

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_all_update()))

    assert len(fake_bot_api.sent_texts) == 1
    text = fake_bot_api.sent_texts[0]
    assert "@alice" in text
    assert 'tg://user?id=2' in text
    assert "Bob" in text
    # Чат без топиков — ответ без message_thread_id.
    assert fake_bot_api.sent_thread_ids == [None]


async def test_all_replies_in_the_topic_it_was_called_from(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(session_factory, project.id, tg_user_id=1, username="alice")

    dispatcher = create_dispatcher(session_factory)
    update = _all_update(message_thread_id=42)

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(update))

    assert fake_bot_api.sent_thread_ids == [42]


async def test_all_excludes_removed_members(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(session_factory, project.id, tg_user_id=1, username="alice")
    await _add_member(
        session_factory,
        project.id,
        tg_user_id=2,
        username="removed_bob",
        status=MembershipStatus.REMOVED,
    )

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_all_update()))

    text = fake_bot_api.sent_texts[0]
    assert "@alice" in text
    assert "removed_bob" not in text


async def test_all_without_project_shows_hint(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_all_update()))

    assert any("не настроен" in text for text in fake_bot_api.sent_texts)


async def test_all_without_members_shows_hint(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _create_project(session_factory)

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_all_update()))

    assert any("нет зарегистрированных" in text for text in fake_bot_api.sent_texts)


async def test_all_throttles_repeated_calls_within_configured_window(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory, all_command_throttle_seconds=180)
    await _add_member(session_factory, project.id, tg_user_id=1, username="alice")

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_all_update(1)))
    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_all_update(2)))

    assert len(fake_bot_api.sent_texts) == 2
    assert "@alice" in fake_bot_api.sent_texts[0]
    assert "недавно" in fake_bot_api.sent_texts[1]


async def test_all_throttle_window_is_configurable_per_project(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Админ выставил ProjectSettings.all_command_throttle_seconds = 0 —
    # повторный вызов сразу же не должен троттлиться.
    project = await _create_project(session_factory, all_command_throttle_seconds=0)
    await _add_member(session_factory, project.id, tg_user_id=1, username="alice")

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_all_update(1)))
    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_all_update(2)))

    assert len(fake_bot_api.sent_texts) == 2
    assert all("@alice" in text for text in fake_bot_api.sent_texts)


async def test_all_splits_long_member_list_into_multiple_messages(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    # Юзернеймы длиной ~30 символов, ~400 участников гарантированно превышают
    # лимит длины сообщения Telegram (4096 символов) и требуют разбивки.
    for i in range(400):
        await _add_member(
            session_factory, project.id, tg_user_id=i, username=f"user_{i:03d}_{'x' * 20}"
        )

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_all_update()))

    assert len(fake_bot_api.sent_texts) > 1
    for text in fake_bot_api.sent_texts:
        assert len(text) <= 4096
    combined = "\n".join(fake_bot_api.sent_texts)
    assert all(f"@user_{i:03d}_{'x' * 20}" in combined for i in range(400))
