from aiogram import Bot
from aiogram.types import Update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.bot import create_dispatcher
from meetup_bot.db.enums import MembershipRole
from meetup_bot.db.models import Project, ProjectMembership, ProjectSettings, User
from tests.conftest import FakeBotApi

_CHAT_ID = -100999
_ADMIN_TG_ID = 100
_MEMBER_TG_ID = 200


def _settings_update(
    args: str = "",
    *,
    update_id: int = 1,
    user_id: int = _ADMIN_TG_ID,
) -> dict:
    text = "/settings" + (f" {args}" if args else "")
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": 1700000000,
            "chat": {"id": _CHAT_ID, "type": "supergroup", "title": "Test Group"},
            "from": {
                "id": user_id,
                "is_bot": False,
                "first_name": "Caller",
                "username": "caller_user",
            },
            "text": text,
            "entities": [{"type": "bot_command", "offset": 0, "length": 9}],
        },
    }


async def _create_project(
    session_factory: async_sessionmaker[AsyncSession],
) -> Project:
    async with session_factory() as session:
        project = Project(
            tg_chat_id=_CHAT_ID, name="Test Group", invite_payload="payload-settings"
        )
        session.add(project)
        await session.flush()
        session.add(ProjectSettings(project_id=project.id))
        await session.commit()
        await session.refresh(project)
        return project


async def _add_member(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: int,
    *,
    tg_user_id: int,
    role: MembershipRole,
) -> None:
    async with session_factory() as session:
        user = User(tg_user_id=tg_user_id, username=f"u{tg_user_id}", first_name="Name")
        session.add(user)
        await session.flush()
        session.add(
            ProjectMembership(project_id=project_id, user_id=user.id, role=role)
        )
        await session.commit()


async def _read_settings(
    session_factory: async_sessionmaker[AsyncSession], project_id: int
) -> ProjectSettings:
    async with session_factory() as session:
        settings = await session.get(ProjectSettings, project_id)
        assert settings is not None
        return settings


async def test_settings_without_args_lists_current_values(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory, project.id, tg_user_id=_ADMIN_TG_ID, role=MembershipRole.ADMIN
    )

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_settings_update()))

    text = fake_bot_api.sent_texts[-1]
    assert "reminder_days_threshold" in text
    assert "missed_events_escalation_count" in text
    assert "reminder_send_hour" in text
    assert "timezone" in text
    assert "Europe/Moscow" in text


async def test_settings_updates_integer_value(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory, project.id, tg_user_id=_ADMIN_TG_ID, role=MembershipRole.ADMIN
    )

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_settings_update("reminder_send_hour 7")),
    )

    assert "20 → 7" in fake_bot_api.sent_texts[-1]
    settings = await _read_settings(session_factory, project.id)
    assert settings.reminder_send_hour == 7


async def test_settings_updates_timezone(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory, project.id, tg_user_id=_ADMIN_TG_ID, role=MembershipRole.ADMIN
    )

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_settings_update("timezone Asia/Novosibirsk")),
    )

    settings = await _read_settings(session_factory, project.id)
    assert settings.timezone == "Asia/Novosibirsk"


async def test_settings_updates_all_command_throttle_seconds(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory, project.id, tg_user_id=_ADMIN_TG_ID, role=MembershipRole.ADMIN
    )

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_settings_update("all_command_throttle_seconds 0")),
    )

    assert "180 → 0" in fake_bot_api.sent_texts[-1]
    settings = await _read_settings(session_factory, project.id)
    assert settings.all_command_throttle_seconds == 0


async def test_settings_rejects_out_of_range_throttle(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory, project.id, tg_user_id=_ADMIN_TG_ID, role=MembershipRole.ADMIN
    )

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(
            _settings_update("all_command_throttle_seconds 99999")
        ),
    )

    assert "от 0 до 3600" in fake_bot_api.sent_texts[-1]
    settings = await _read_settings(session_factory, project.id)
    assert settings.all_command_throttle_seconds == 180


async def test_settings_rejects_out_of_range_integer(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory, project.id, tg_user_id=_ADMIN_TG_ID, role=MembershipRole.ADMIN
    )

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_settings_update("reminder_send_hour 42")),
    )

    assert "от 0 до 23" in fake_bot_api.sent_texts[-1]
    settings = await _read_settings(session_factory, project.id)
    assert settings.reminder_send_hour == 20


async def test_settings_rejects_unknown_timezone(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory, project.id, tg_user_id=_ADMIN_TG_ID, role=MembershipRole.ADMIN
    )

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_settings_update("timezone Mars/Olympus")),
    )

    assert "таймзону" in fake_bot_api.sent_texts[-1]
    settings = await _read_settings(session_factory, project.id)
    assert settings.timezone == "Europe/Moscow"


async def test_settings_rejects_unknown_key(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory, project.id, tg_user_id=_ADMIN_TG_ID, role=MembershipRole.ADMIN
    )

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_settings_update("nonsense 5")),
    )

    assert "Неизвестный параметр" in fake_bot_api.sent_texts[-1]


async def test_settings_key_without_value_asks_for_value(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory, project.id, tg_user_id=_ADMIN_TG_ID, role=MembershipRole.ADMIN
    )

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_settings_update("reminder_send_hour")),
    )

    assert "Укажите новое значение" in fake_bot_api.sent_texts[-1]


async def test_settings_same_value_is_noop(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory, project.id, tg_user_id=_ADMIN_TG_ID, role=MembershipRole.ADMIN
    )

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_settings_update("reminder_send_hour 20")),
    )

    assert "уже равен" in fake_bot_api.sent_texts[-1]


async def test_settings_requires_admin(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    await _add_member(
        session_factory, project.id, tg_user_id=_MEMBER_TG_ID, role=MembershipRole.MEMBER
    )

    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(
            _settings_update("reminder_send_hour 7", user_id=_MEMBER_TG_ID)
        ),
    )

    assert "только администратор" in fake_bot_api.sent_texts[-1]
    settings = await _read_settings(session_factory, project.id)
    assert settings.reminder_send_hour == 20


async def test_settings_without_project_shows_hint(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dispatcher = create_dispatcher(session_factory)
    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_settings_update()))

    assert "не настроен" in fake_bot_api.sent_texts[-1]
