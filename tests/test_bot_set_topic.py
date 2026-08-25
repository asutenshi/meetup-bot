from aiogram import Bot
from aiogram.types import Update
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.bot import create_dispatcher
from meetup_bot.bot.handlers import set_topic
from meetup_bot.db.enums import MembershipRole, TopicCategory
from meetup_bot.db.models import Project, ProjectMembership, ProjectTopicSetting, User
from tests.conftest import FakeBotApi

_CHAT_ID = -100999
_ADMIN_ID = 555
_MEMBER_ID = 777


def _set_topic_update(
    update_id: int = 1,
    *,
    chat_id: int = _CHAT_ID,
    user_id: int = _ADMIN_ID,
    username: str = "admin_user",
    args: str = "events",
    is_forum: bool = True,
    message_thread_id: int | None = 7,
) -> dict:
    text = f"/set_topic {args}".rstrip()
    message: dict = {
        "message_id": update_id,
        "date": 1700000000,
        "chat": {
            "id": chat_id,
            "type": "supergroup",
            "title": "Test Group",
            "is_forum": is_forum,
        },
        "from": {
            "id": user_id,
            "is_bot": False,
            "first_name": "User",
            "username": username,
        },
        "text": text,
        "entities": [{"type": "bot_command", "offset": 0, "length": len("/set_topic")}],
    }
    if message_thread_id is not None:
        message["message_thread_id"] = message_thread_id
        message["is_topic_message"] = True
    return {"update_id": update_id, "message": message}


async def _create_project_with_admin(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    chat_id: int = _CHAT_ID,
) -> Project:
    async with session_factory() as session:
        project = Project(
            tg_chat_id=chat_id, name="Test Group", invite_payload=f"payload-{chat_id}"
        )
        session.add(project)
        await session.flush()
        admin = User(tg_user_id=_ADMIN_ID, username="admin_user", first_name="Admin")
        session.add(admin)
        await session.flush()
        session.add(
            ProjectMembership(
                project_id=project.id, user_id=admin.id, role=MembershipRole.ADMIN
            )
        )
        await session.commit()
        await session.refresh(project)
        return project


async def test_set_topic_by_admin_creates_setting(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project_with_admin(session_factory)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_set_topic_update(args="events"))
    )

    async with session_factory() as session:
        setting = await session.scalar(
            select(ProjectTopicSetting).where(
                ProjectTopicSetting.project_id == project.id,
                ProjectTopicSetting.category == TopicCategory.EVENTS,
            )
        )
    assert setting is not None
    assert setting.thread_id == 7
    assert any("анонсироваться" in text for text in fake_bot_api.sent_texts)


async def test_repeated_call_updates_existing_setting(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project_with_admin(session_factory)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(
            _set_topic_update(1, args="events", message_thread_id=7)
        ),
    )
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(
            _set_topic_update(2, args="events", message_thread_id=9)
        ),
    )

    async with session_factory() as session:
        settings = (
            await session.scalars(
                select(ProjectTopicSetting).where(
                    ProjectTopicSetting.project_id == project.id,
                    ProjectTopicSetting.category == TopicCategory.EVENTS,
                )
            )
        ).all()

    assert len(settings) == 1
    assert settings[0].thread_id == 9


async def test_repeated_call_in_same_topic_notifies_already_assigned(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _create_project_with_admin(session_factory)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(
            _set_topic_update(1, args="events", message_thread_id=7)
        ),
    )
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(
            _set_topic_update(2, args="events", message_thread_id=7)
        ),
    )

    assert fake_bot_api.sent_texts[0].startswith("Готово!")
    assert "уже назначен" in fake_bot_api.sent_texts[1]


async def test_set_topic_by_non_admin_is_rejected(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project_with_admin(session_factory)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(
            _set_topic_update(user_id=_MEMBER_ID, username="random_member")
        ),
    )

    async with session_factory() as session:
        settings = (await session.scalars(select(ProjectTopicSetting))).all()
    assert settings == []
    assert project is not None
    assert any("только администратор" in text for text in fake_bot_api.sent_texts)


async def test_set_topic_without_project_asks_for_setup(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_set_topic_update())
    )

    assert any("/setup_registration" in text for text in fake_bot_api.sent_texts)


async def test_set_topic_in_non_forum_chat_is_rejected(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _create_project_with_admin(session_factory)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_set_topic_update(is_forum=False)),
    )

    async with session_factory() as session:
        settings = (await session.scalars(select(ProjectTopicSetting))).all()
    assert settings == []
    assert any("нет топиков" in text for text in fake_bot_api.sent_texts)


async def test_set_topic_outside_topic_is_rejected(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _create_project_with_admin(session_factory)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_set_topic_update(message_thread_id=None)),
    )

    async with session_factory() as session:
        settings = (await session.scalars(select(ProjectTopicSetting))).all()
    assert settings == []
    assert any("Вызовите эту команду внутри топика" in text for text in fake_bot_api.sent_texts)


async def test_set_topic_with_invalid_category_lists_valid_ones(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _create_project_with_admin(session_factory)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_set_topic_update(args="not_a_category")),
    )

    async with session_factory() as session:
        settings = (await session.scalars(select(ProjectTopicSetting))).all()
    assert settings == []
    assert any(
        "events, money_collections, general" in text for text in fake_bot_api.sent_texts
    )


def test_texts_are_safe_for_default_html_parse_mode() -> None:
    # Бот создаётся с parse_mode=HTML по умолчанию (`bot/__init__.py`) — `<...>`
    # в тексте (например, плейсхолдер `<category>`) Telegram пытается
    # распарсить как тег и роняет `sendMessage` с `TelegramBadRequest`.
    texts = [
        set_topic._NOT_SET_UP_TEXT,
        set_topic._NOT_ADMIN_TEXT,
        set_topic._NOT_FORUM_TEXT,
        set_topic._OUTSIDE_TOPIC_TEXT,
        set_topic._INVALID_CATEGORY_TEXT,
        *set_topic._CONFIRMATION_TEXT.values(),
        *set_topic._ALREADY_ASSIGNED_TEXT.values(),
    ]
    assert all("<" not in text for text in texts)
