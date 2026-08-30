import datetime

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, Update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.bot import create_dispatcher
from meetup_bot.bot.handlers.cancel_event import (
    _ABORTED_TEXT,
    _NO_ACCESS_TEXT,
    _STALE_TEXT,
)
from meetup_bot.config import Settings
from meetup_bot.db.enums import EventStatus, MembershipRole, RSVPStatus
from meetup_bot.db.models import (
    Event,
    EventCoOrganizer,
    EventRSVP,
    Project,
    ProjectMembership,
    ProjectSettings,
    User,
)
from tests.conftest import BOT_TOKEN, FakeBotApi

_USER_ID = 555
_GOING_TG_ID = 778
_START = datetime.datetime(2026, 11, 5, 19, 0, tzinfo=datetime.UTC)


def _settings() -> Settings:
    return Settings(
        bot_token=BOT_TOKEN,
        database_url="sqlite+aiosqlite:///:memory:",
        public_base_url="https://example.com",
    )


def _command_update(update_id: int = 1, *, chat_type: str = "private") -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": 1700000000,
            "chat": {"id": _USER_ID, "type": chat_type, "first_name": "Member"},
            "from": {
                "id": _USER_ID,
                "is_bot": False,
                "first_name": "Member",
                "username": "member_user",
            },
            "text": "/cancel_event",
            "entities": [
                {"type": "bot_command", "offset": 0, "length": len("/cancel_event")}
            ],
        },
    }


def _callback_update(data: str, update_id: int = 2, *, user_id: int = _USER_ID) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cb{update_id}",
            "from": {
                "id": user_id,
                "is_bot": False,
                "first_name": "Member",
                "username": "member_user",
            },
            "message": {
                "message_id": 2000,
                "date": 1700000000,
                "chat": {"id": _USER_ID, "type": "private", "first_name": "Member"},
                "text": "placeholder",
            },
            "chat_instance": "1",
            "data": data,
        },
    }


async def _seed(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    role: MembershipRole = MembershipRole.MEMBER,
    caller_is_creator: bool = True,
    co_organizer_other: bool = False,
    status: EventStatus = EventStatus.PLANNED,
    finalized: bool = False,
    with_going: bool = True,
    announcement_message_id: int | None = 900,
) -> dict[str, int]:
    async with session_factory() as session:
        project = Project(tg_chat_id=-100101, name="Alpha", invite_payload="alpha-pl")
        session.add(project)
        await session.flush()
        session.add(ProjectSettings(project_id=project.id, timezone="Europe/Moscow"))

        caller = User(tg_user_id=_USER_ID, first_name="Member", username="member_user")
        other = User(tg_user_id=777, first_name="Создатель")
        going = User(tg_user_id=_GOING_TG_ID, first_name="Гость", username="guest")
        session.add_all([caller, other, going])
        await session.flush()
        session.add_all(
            [
                ProjectMembership(project_id=project.id, user_id=caller.id, role=role),
                ProjectMembership(
                    project_id=project.id, user_id=other.id, role=MembershipRole.MEMBER
                ),
                ProjectMembership(
                    project_id=project.id, user_id=going.id, role=MembershipRole.MEMBER
                ),
            ]
        )

        event = Event(
            project_id=project.id,
            description="встреча",
            starts_at=_START,
            location="Парк",
            status=status,
            created_by=caller.id if caller_is_creator else other.id,
            announcement_message_id=announcement_message_id,
            attendance_finalized_at=(
                datetime.datetime(2026, 11, 10, tzinfo=datetime.UTC) if finalized else None
            ),
        )
        session.add(event)
        await session.flush()
        if co_organizer_other:
            session.add(EventCoOrganizer(event_id=event.id, user_id=other.id))
        if with_going:
            session.add(
                EventRSVP(
                    event_id=event.id,
                    user_id=going.id,
                    status=RSVPStatus.GOING,
                    updated_by=going.id,
                )
            )
        await session.commit()
        return {"project_id": project.id, "event_id": event.id}


def _callback_datas(markup: InlineKeyboardMarkup | None) -> list[str]:
    assert markup is not None
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]


async def test_cancel_event_lists_event_with_callback_button(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    ids = await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_command_update()))

    message = fake_bot_api.sent_messages[-1]
    assert _callback_datas(message.reply_markup) == [f"cev:{ids['event_id']}"]


async def test_cancel_event_full_flow_marks_cancelled_and_notifies(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    ids = await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_command_update()))
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_callback_update(f"cev:{ids['event_id']}", 2)),
    )
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_callback_update(f"cec:{ids['event_id']}", 3)),
    )

    async with session_factory() as session:
        event = await session.get(Event, ids["event_id"])
        assert event is not None
        assert event.status == EventStatus.CANCELLED

    # Анонс перерисован без клавиатуры и с пометкой.
    edited = fake_bot_api.edited_messages
    announcement = next(m for m in edited if m.message_id == 900)
    assert announcement.reply_markup is None
    assert "🚫 <b>Мероприятие отменено</b>" in (announcement.text or "")

    # Подтвердивший участие получил личное уведомление.
    assert any("🚫 Отменено" in t for t in fake_bot_api.sent_texts)
    result = fake_bot_api.edited_texts[-1]
    assert result.startswith("Мероприятие отменено")
    assert "уведомление: 1" in result
    assert "RSVP-кнопки убраны" in result


async def test_cancel_event_warns_when_announcement_cannot_be_updated(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    ids = await _seed(session_factory, announcement_message_id=None)
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_command_update()))
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_callback_update(f"cev:{ids['event_id']}", 2)),
    )
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_callback_update(f"cec:{ids['event_id']}", 3)),
    )

    async with session_factory() as session:
        event = await session.get(Event, ids["event_id"])
        assert event is not None
        assert event.status == EventStatus.CANCELLED

    # Анонс не трогали (в сид не клали announcement_message_id).
    assert not any(m.message_id == 900 for m in fake_bot_api.edited_messages)
    result = fake_bot_api.edited_texts[-1]
    assert result.startswith("Мероприятие отменено")
    assert "обновить не удалось" in result


async def test_cancel_event_abort_keeps_event_planned(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    ids = await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_command_update()))
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_callback_update(f"cev:{ids['event_id']}", 2)),
    )
    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_callback_update("cex", 3))
    )

    async with session_factory() as session:
        event = await session.get(Event, ids["event_id"])
        assert event is not None
        assert event.status == EventStatus.PLANNED
    assert fake_bot_api.edited_texts[-1] == _ABORTED_TEXT


async def test_cancel_event_rejects_forged_callback_without_right(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # Вызвавший — не создатель и не организатор, обычный участник.
    ids = await _seed(session_factory, caller_is_creator=False, co_organizer_other=True)
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_callback_update(f"cec:{ids['event_id']}", 1)),
    )

    assert fake_bot_api.callback_answers[-1] == _NO_ACCESS_TEXT
    async with session_factory() as session:
        event = await session.get(Event, ids["event_id"])
        assert event is not None
        assert event.status == EventStatus.PLANNED


async def test_cancel_event_pick_of_already_cancelled_is_stale(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    ids = await _seed(session_factory, status=EventStatus.CANCELLED)
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_callback_update(f"cev:{ids['event_id']}", 1)),
    )

    assert fake_bot_api.callback_answers[-1] == _STALE_TEXT


async def test_cancel_event_list_skips_cancelled_and_finalized(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _seed(session_factory, finalized=True)
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_command_update()))

    assert any("Нет мероприятий" in t for t in fake_bot_api.sent_texts)


async def test_cancel_event_without_projects_shows_hint(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_command_update()))

    assert any("не состоите ни в одном проекте" in t for t in fake_bot_api.sent_texts)


async def test_cancel_event_ignored_outside_private_chat(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_command_update(chat_type="supergroup")),
    )

    assert fake_bot_api.sent_texts == []


async def test_cancel_event_admin_can_cancel_event_without_organizer(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    ids = await _seed(
        session_factory, role=MembershipRole.ADMIN, caller_is_creator=False
    )
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_command_update()))
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_callback_update(f"cev:{ids['event_id']}", 2)),
    )
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_callback_update(f"cec:{ids['event_id']}", 3)),
    )

    async with session_factory() as session:
        event = await session.get(Event, ids["event_id"])
        assert event is not None
        assert event.status == EventStatus.CANCELLED
