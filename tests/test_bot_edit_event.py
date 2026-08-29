import datetime

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, Update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.bot import create_dispatcher
from meetup_bot.config import Settings
from meetup_bot.db.enums import EventStatus, MembershipRole
from meetup_bot.db.models import (
    Event,
    EventCoOrganizer,
    Project,
    ProjectMembership,
    User,
)
from tests.conftest import BOT_TOKEN, FakeBotApi

_USER_ID = 555
_START = datetime.datetime(2026, 11, 5, 19, 0, tzinfo=datetime.UTC)


def _settings(public_base_url: str | None = "https://example.com") -> Settings:
    return Settings(
        bot_token=BOT_TOKEN,
        database_url="sqlite+aiosqlite:///:memory:",
        public_base_url=public_base_url,
    )


def _edit_event_update(update_id: int = 1, *, chat_type: str = "private") -> dict:
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
            "text": "/edit_event",
            "entities": [
                {"type": "bot_command", "offset": 0, "length": len("/edit_event")}
            ],
        },
    }


async def _seed(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    role: MembershipRole = MembershipRole.MEMBER,
    caller_is_creator: bool = True,
    co_organizer_other: bool = False,
) -> dict[str, int]:
    async with session_factory() as session:
        project = Project(tg_chat_id=-100101, name="Alpha", invite_payload="alpha-pl")
        session.add(project)
        await session.flush()

        caller = User(tg_user_id=_USER_ID, first_name="Member", username="member_user")
        creator = User(tg_user_id=777, first_name="Создатель")
        session.add_all([caller, creator])
        await session.flush()
        session.add_all(
            [
                ProjectMembership(project_id=project.id, user_id=caller.id, role=role),
                ProjectMembership(
                    project_id=project.id, user_id=creator.id, role=MembershipRole.MEMBER
                ),
            ]
        )

        event = Event(
            project_id=project.id,
            description="встреча",
            starts_at=_START,
            location="Парк",
            created_by=caller.id if caller_is_creator else creator.id,
        )
        session.add(event)
        await session.flush()
        if co_organizer_other:
            session.add(EventCoOrganizer(event_id=event.id, user_id=creator.id))
        await session.commit()
        return {"project_id": project.id, "event_id": event.id}


def _web_app_urls(markup: InlineKeyboardMarkup | None) -> list[str]:
    assert markup is not None
    return [
        button.web_app.url
        for row in markup.inline_keyboard
        for button in row
        if button.web_app is not None
    ]


async def test_edit_event_lists_event_with_web_app_button(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    ids = await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_edit_event_update()))

    message = fake_bot_api.sent_messages[-1]
    assert _web_app_urls(message.reply_markup) == [
        f"https://example.com/app/?project=alpha-pl&event={ids['event_id']}"
    ]


async def test_edit_event_hides_event_without_right(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # Вызвавший — не создатель и не организатор, обычный участник.
    await _seed(session_factory, caller_is_creator=False, co_organizer_other=True)
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_edit_event_update()))

    assert any("Нет мероприятий" in t for t in fake_bot_api.sent_texts)


async def test_edit_event_admin_sees_event_without_organizer(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _seed(session_factory, role=MembershipRole.ADMIN, caller_is_creator=False)
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_edit_event_update()))

    assert _web_app_urls(fake_bot_api.sent_messages[-1].reply_markup)


async def test_edit_event_skips_cancelled_and_finalized(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    ids = await _seed(session_factory)
    async with session_factory() as session:
        event = await session.get(Event, ids["event_id"])
        assert event is not None
        event.status = EventStatus.CANCELLED
        await session.commit()
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_edit_event_update()))

    assert any("Нет мероприятий" in t for t in fake_bot_api.sent_texts)


async def test_edit_event_without_projects_shows_hint(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_edit_event_update()))

    assert any("не состоите ни в одном проекте" in t for t in fake_bot_api.sent_texts)


async def test_edit_event_not_configured_without_public_base_url(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory, _settings(public_base_url=None))

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_edit_event_update()))

    assert any("не настроен публичный адрес Web App" in t for t in fake_bot_api.sent_texts)


async def test_edit_event_ignored_outside_private_chat(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_edit_event_update(chat_type="supergroup"))
    )

    assert fake_bot_api.sent_texts == []


async def test_edit_event_co_organizer_sees_only_their_event(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # Событие создано другим, вызвавший добавлен со-организатором.
    async with session_factory() as session:
        project = Project(tg_chat_id=-100777, name="Beta", invite_payload="beta-pl")
        session.add(project)
        await session.flush()
        caller = User(tg_user_id=_USER_ID, first_name="Member", username="member_user")
        creator = User(tg_user_id=888, first_name="Кто-то")
        session.add_all([caller, creator])
        await session.flush()
        session.add_all(
            [
                ProjectMembership(
                    project_id=project.id, user_id=caller.id, role=MembershipRole.MEMBER
                ),
                ProjectMembership(
                    project_id=project.id, user_id=creator.id, role=MembershipRole.MEMBER
                ),
            ]
        )
        mine = Event(
            project_id=project.id,
            description="моё",
            starts_at=_START,
            location="A",
            created_by=creator.id,
        )
        theirs = Event(
            project_id=project.id,
            description="чужое",
            starts_at=_START,
            location="B",
            created_by=creator.id,
        )
        session.add_all([mine, theirs])
        await session.flush()
        session.add(EventCoOrganizer(event_id=mine.id, user_id=caller.id))
        session.add(EventCoOrganizer(event_id=theirs.id, user_id=creator.id))
        await session.commit()
        mine_id = mine.id

    dispatcher = create_dispatcher(session_factory, _settings())
    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_edit_event_update()))

    urls = _web_app_urls(fake_bot_api.sent_messages[-1].reply_markup)
    assert urls == [f"https://example.com/app/?project=beta-pl&event={mine_id}"]
