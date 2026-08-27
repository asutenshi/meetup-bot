from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, Update
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.bot import create_dispatcher
from meetup_bot.config import Settings
from meetup_bot.db.enums import MembershipRole, MembershipStatus
from meetup_bot.db.models import Project, ProjectMembership, User
from tests.conftest import BOT_TOKEN, FakeBotApi

_USER_ID = 555


def _settings(public_base_url: str | None = "https://example.com") -> Settings:
    return Settings(
        bot_token=BOT_TOKEN,
        database_url="sqlite+aiosqlite:///:memory:",
        public_base_url=public_base_url,
    )


def _new_event_update(update_id: int = 1, *, chat_type: str = "private") -> dict:
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
            "text": "/new_event",
            "entities": [{"type": "bot_command", "offset": 0, "length": len("/new_event")}],
        },
    }


def _callback_update(data: str, update_id: int = 2) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": "cb1",
            "from": {
                "id": _USER_ID,
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


async def _add_project(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    name: str,
    payload: str,
    chat_id: int,
    member_tg_id: int | None = _USER_ID,
    member_status: MembershipStatus = MembershipStatus.ACTIVE,
    is_active: bool = True,
) -> Project:
    async with session_factory() as session:
        project = Project(
            tg_chat_id=chat_id, name=name, invite_payload=payload, is_active=is_active
        )
        session.add(project)
        await session.flush()
        if member_tg_id is not None:
            user = await session.scalar(select(User).where(User.tg_user_id == member_tg_id))
            if user is None:
                user = User(
                    tg_user_id=member_tg_id, username="member_user", first_name="Member"
                )
                session.add(user)
                await session.flush()
            session.add(
                ProjectMembership(
                    project_id=project.id,
                    user_id=user.id,
                    role=MembershipRole.MEMBER,
                    status=member_status,
                )
            )
        await session.commit()
        await session.refresh(project)
        return project


def _web_app_urls(markup: InlineKeyboardMarkup | None) -> list[str]:
    assert markup is not None
    return [
        button.web_app.url
        for row in markup.inline_keyboard
        for button in row
        if button.web_app is not None
    ]


async def test_new_event_single_project_sends_web_app_button(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _add_project(session_factory, name="Alpha", payload="alpha-pl", chat_id=-100001)
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_new_event_update()))

    message = fake_bot_api.sent_messages[-1]
    assert "Alpha" in (message.text or "")
    assert _web_app_urls(message.reply_markup) == [
        "https://example.com/app/?project=alpha-pl"
    ]


async def test_new_event_multiple_projects_prompts_choice_then_opens_form(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _add_project(session_factory, name="Alpha", payload="alpha-pl", chat_id=-100001)
    beta = await _add_project(session_factory, name="Beta", payload="beta-pl", chat_id=-100002)
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_new_event_update()))

    prompt = fake_bot_api.sent_messages[-1]
    # Выбор проекта — обычные callback-кнопки, не web_app (URL проекта ещё не выбран).
    assert _web_app_urls(prompt.reply_markup) == []
    assert prompt.reply_markup is not None
    buttons = [b for row in prompt.reply_markup.inline_keyboard for b in row]
    assert {b.text for b in buttons} == {"Alpha", "Beta"}

    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_callback_update(f"nev:{beta.id}"))
    )

    edited = fake_bot_api.edited_messages[-1]
    assert "Beta" in (edited.text or "")
    assert _web_app_urls(edited.reply_markup) == ["https://example.com/app/?project=beta-pl"]


async def test_new_event_without_projects_shows_hint(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_new_event_update()))

    assert any("не состоите ни в одном проекте" in t for t in fake_bot_api.sent_texts)
    assert fake_bot_api.sent_messages[-1].reply_markup is None


async def test_new_event_removed_member_is_not_offered_project(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _add_project(
        session_factory,
        name="Alpha",
        payload="alpha-pl",
        chat_id=-100001,
        member_status=MembershipStatus.REMOVED,
    )
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_new_event_update()))

    assert any("не состоите ни в одном проекте" in t for t in fake_bot_api.sent_texts)


async def test_new_event_not_configured_without_public_base_url(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _add_project(session_factory, name="Alpha", payload="alpha-pl", chat_id=-100001)
    dispatcher = create_dispatcher(session_factory, _settings(public_base_url=None))

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_new_event_update()))

    assert any("не настроен публичный адрес Web App" in t for t in fake_bot_api.sent_texts)


async def test_new_event_ignored_outside_private_chat(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _add_project(session_factory, name="Alpha", payload="alpha-pl", chat_id=-100001)
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_new_event_update(chat_type="supergroup")),
    )

    assert fake_bot_api.sent_texts == []


async def test_new_event_pick_stale_project_shows_alert(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _add_project(session_factory, name="Alpha", payload="alpha-pl", chat_id=-100001)
    beta = await _add_project(session_factory, name="Beta", payload="beta-pl", chat_id=-100002)
    dispatcher = create_dispatcher(session_factory, _settings())

    await dispatcher.feed_update(bot=bot, update=Update.model_validate(_new_event_update()))

    # Участника убрали из Beta уже после того, как бот показал список выбора.
    async with session_factory() as session:
        membership = await session.scalar(
            select(ProjectMembership).where(ProjectMembership.project_id == beta.id)
        )
        assert membership is not None
        membership.status = MembershipStatus.REMOVED
        await session.commit()

    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_callback_update(f"nev:{beta.id}"))
    )

    assert any("больше недоступен" in t for t in fake_bot_api.callback_answers)
    assert fake_bot_api.edited_messages == []
