from aiogram import Bot
from aiogram.types import Update
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.bot import create_dispatcher
from meetup_bot.db.enums import MembershipRole, MembershipStatus
from meetup_bot.db.models import Project, ProjectMembership, User
from tests.conftest import FakeBotApi


def _start_update(
    update_id: int = 1,
    user_id: int = 777,
    payload: str | None = None,
) -> dict:
    text = f"/start {payload}" if payload else "/start"
    entity_length = len("/start")
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": 1700000000,
            "chat": {"id": user_id, "type": "private", "first_name": "Member"},
            "from": {
                "id": user_id,
                "is_bot": False,
                "first_name": "Member",
                "username": "member_user",
            },
            "text": text,
            "entities": [{"type": "bot_command", "offset": 0, "length": entity_length}],
        },
    }


async def _create_project(
    session_factory: async_sessionmaker[AsyncSession], *, invite_payload: str = "abc123"
) -> Project:
    async with session_factory() as session:
        project = Project(
            tg_chat_id=-100999,
            name="Test Group",
            invite_payload=invite_payload,
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return project


async def test_start_with_valid_payload_registers_member(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    dispatcher = create_dispatcher(session_factory)
    update = Update.model_validate(_start_update(payload=project.invite_payload))

    await dispatcher.feed_update(bot=bot, update=update)

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.tg_user_id == 777))
        assert user is not None
        assert user.username == "member_user"

        membership = await session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project.id,
                ProjectMembership.user_id == user.id,
            )
        )
        assert membership is not None
        assert membership.role == MembershipRole.MEMBER
        assert membership.status == MembershipStatus.ACTIVE

    assert any("Test Group" in text for text in fake_bot_api.sent_texts)


async def test_repeated_start_with_same_payload_is_idempotent(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project = await _create_project(session_factory)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_start_update(1, payload=project.invite_payload))
    )
    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_start_update(2, payload=project.invite_payload))
    )

    async with session_factory() as session:
        memberships = (await session.scalars(select(ProjectMembership))).all()

    assert len(memberships) == 1


async def test_start_without_payload_shows_hint(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dispatcher = create_dispatcher(session_factory)
    update = Update.model_validate(_start_update())

    await dispatcher.feed_update(bot=bot, update=update)

    async with session_factory() as session:
        users = (await session.scalars(select(User))).all()

    assert users == []
    assert any("ссылке из поста" in text for text in fake_bot_api.sent_texts)


async def test_start_with_unknown_payload_shows_error(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dispatcher = create_dispatcher(session_factory)
    update = Update.model_validate(_start_update(payload="does-not-exist"))

    await dispatcher.feed_update(bot=bot, update=update)

    async with session_factory() as session:
        users = (await session.scalars(select(User))).all()

    assert users == []
    assert any("недействительна" in text for text in fake_bot_api.sent_texts)
