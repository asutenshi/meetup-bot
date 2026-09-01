import datetime

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, Update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.bot import create_dispatcher
from meetup_bot.config import Settings
from meetup_bot.db.enums import EventStatus, MembershipRole
from meetup_bot.db.models import Event, Project, ProjectMembership, User
from tests.conftest import BOT_TOKEN, FakeBotApi

_USER_ID = 555
_NOW = datetime.datetime(2026, 9, 1, 12, 0, tzinfo=datetime.UTC)


def _settings(public_base_url: str | None = "https://example.com") -> Settings:
    return Settings(
        bot_token=BOT_TOKEN,
        database_url="sqlite+aiosqlite:///:memory:",
        public_base_url=public_base_url,
    )


def _attendance_update(update_id: int = 1, *, chat_type: str = "private") -> dict:
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
            "text": "/attendance",
            "entities": [
                {"type": "bot_command", "offset": 0, "length": len("/attendance")}
            ],
        },
    }


async def _seed(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    async with session_factory() as session:
        project = Project(tg_chat_id=-100101, name="Alpha", invite_payload="alpha-pl")
        session.add(project)
        await session.flush()
        caller = User(tg_user_id=_USER_ID, first_name="Member", username="member_user")
        session.add(caller)
        await session.flush()
        session.add(
            ProjectMembership(
                project_id=project.id, user_id=caller.id, role=MembershipRole.OWNER
            )
        )
        finalized = Event(
            project_id=project.id,
            description="прошедшее",
            starts_at=_NOW - datetime.timedelta(days=3),
            location="Парк",
            created_by=caller.id,
            attendance_finalized_at=_NOW - datetime.timedelta(days=2),
        )
        upcoming = Event(
            project_id=project.id,
            description="будущее",
            starts_at=_NOW + datetime.timedelta(days=4),
            location="Клуб",
            created_by=caller.id,
        )
        cancelled = Event(
            project_id=project.id,
            description="отменённое",
            starts_at=_NOW + datetime.timedelta(days=2),
            location="Кафе",
            created_by=caller.id,
            status=EventStatus.CANCELLED,
        )
        session.add_all([finalized, upcoming, cancelled])
        await session.flush()
        await session.commit()
        return {
            "project_id": project.id,
            "finalized_id": finalized.id,
            "upcoming_id": upcoming.id,
        }


def _web_app_urls(markup: InlineKeyboardMarkup | None) -> list[str]:
    assert markup is not None
    return [
        button.web_app.url
        for row in markup.inline_keyboard
        for button in row
        if button.web_app is not None
    ]


async def test_attendance_lists_upcoming_and_finalized_not_cancelled(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    ids = await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_attendance_update())
    )

    urls = _web_app_urls(fake_bot_api.sent_messages[-1].reply_markup)
    assert urls == [
        f"https://example.com/app/?project=alpha-pl&attendance={ids['upcoming_id']}",
        f"https://example.com/app/?project=alpha-pl&attendance={ids['finalized_id']}",
    ]


async def test_attendance_hides_events_without_right(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        project = Project(tg_chat_id=-100202, name="Beta", invite_payload="beta-pl")
        session.add(project)
        await session.flush()
        caller = User(tg_user_id=_USER_ID, first_name="Member")
        creator = User(tg_user_id=777, first_name="Создатель")
        session.add_all([caller, creator])
        await session.flush()
        session.add_all(
            [
                ProjectMembership(
                    project_id=project.id, user_id=caller.id, role=MembershipRole.MEMBER
                ),
                ProjectMembership(
                    project_id=project.id,
                    user_id=creator.id,
                    role=MembershipRole.MEMBER,
                ),
            ]
        )
        session.add(
            Event(
                project_id=project.id,
                description="чужое",
                starts_at=_NOW + datetime.timedelta(days=1),
                location="X",
                created_by=creator.id,
            )
        )
        await session.commit()
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_attendance_update())
    )

    assert any("Нет мероприятий" in t for t in fake_bot_api.sent_texts)


async def test_attendance_ignored_outside_private_chat(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_attendance_update(chat_type="supergroup")),
    )

    assert fake_bot_api.sent_texts == []


async def test_attendance_not_configured_without_public_base_url(
    bot: Bot, fake_bot_api: FakeBotApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory, _settings(public_base_url=None))

    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_attendance_update())
    )

    assert any("не настроен публичный адрес Web App" in t for t in fake_bot_api.sent_texts)
