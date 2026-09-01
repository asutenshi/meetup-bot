"""`/start` по deep-link из-под RSVP-кнопки анонса (`?start=<invite>_<event>_<g|n>`):
регистрация незарегистрированного участника + простановка RSVP за один переход
(техдолг «RSVP от незарегистрированного участника»)."""

import datetime

from aiogram import Bot
from aiogram.types import Update
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.bot import create_dispatcher
from meetup_bot.db.enums import (
    EventStatus,
    MembershipRole,
    MembershipStatus,
    RSVPStatus,
)
from meetup_bot.db.models import (
    Event,
    EventRSVP,
    Project,
    ProjectMembership,
    ProjectSettings,
    User,
)
from tests.conftest import FakeBotApi

_USER_TG_ID = 777
_STARTS_AT = datetime.datetime(2026, 9, 14, 15, 0, tzinfo=datetime.UTC)


def _start_update(payload: str, *, update_id: int = 1) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": 1700000000,
            "chat": {"id": _USER_TG_ID, "type": "private", "first_name": "Member"},
            "from": {
                "id": _USER_TG_ID,
                "is_bot": False,
                "first_name": "Member",
                "username": "member_user",
            },
            "text": f"/start {payload}",
            "entities": [{"type": "bot_command", "offset": 0, "length": len("/start")}],
        },
    }


async def _seed(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    status: EventStatus = EventStatus.PLANNED,
    finalized: bool = False,
    invite_payload: str = "alpha",
    announcement_message_id: int | None = 4242,
) -> dict[str, int]:
    async with session_factory() as session:
        project = Project(
            tg_chat_id=-100_500, name="Alpha", invite_payload=invite_payload
        )
        session.add(project)
        await session.flush()
        session.add(ProjectSettings(project_id=project.id, timezone="Europe/Moscow"))

        owner = User(tg_user_id=111, first_name="Оля", username="olya")
        session.add(owner)
        await session.flush()
        session.add(
            ProjectMembership(
                project_id=project.id, user_id=owner.id, role=MembershipRole.OWNER
            )
        )

        event = Event(
            project_id=project.id,
            title="Прогулка",
            description="Вечерняя прогулка",
            starts_at=_STARTS_AT,
            location="Парк",
            status=status,
            created_by=owner.id,
            announcement_message_id=announcement_message_id,
            attendance_finalized_at=(
                datetime.datetime(2026, 9, 16, tzinfo=datetime.UTC)
                if finalized
                else None
            ),
        )
        session.add(event)
        await session.flush()
        await session.commit()
        return {"project_id": project.id, "event_id": event.id}


async def _rsvp_of_new_user(
    session_factory: async_sessionmaker[AsyncSession], event_id: int
) -> EventRSVP | None:
    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.tg_user_id == _USER_TG_ID))
        if user is None:
            return None
        return await session.scalar(
            select(EventRSVP).where(
                EventRSVP.event_id == event_id, EventRSVP.user_id == user.id
            )
        )


async def test_deeplink_registers_and_sets_going(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_start_update(f"alpha_{ids['event_id']}_g")),
    )

    async with session_factory() as session:
        membership = await session.scalar(
            select(ProjectMembership)
            .join(User, User.id == ProjectMembership.user_id)
            .where(User.tg_user_id == _USER_TG_ID)
        )
        assert membership is not None
        assert membership.role == MembershipRole.MEMBER
        assert membership.status == MembershipStatus.ACTIVE

    rsvp = await _rsvp_of_new_user(session_factory, ids["event_id"])
    assert rsvp is not None
    assert rsvp.status == RSVPStatus.GOING
    assert rsvp.updated_by == rsvp.user_id

    # Анонс перерисован общим `refresh_event_announcement`.
    assert fake_bot_api.edited_messages
    assert "✅ Участвует: 1" in (fake_bot_api.edited_messages[-1].text or "")

    reply = fake_bot_api.sent_texts[-1]
    assert "Вы зарегистрированы в проекте «Alpha»" in reply
    assert "«Прогулка»" in reply
    assert "✅" in reply


async def test_deeplink_sets_not_going(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_start_update(f"alpha_{ids['event_id']}_n")),
    )

    rsvp = await _rsvp_of_new_user(session_factory, ids["event_id"])
    assert rsvp is not None
    assert rsvp.status == RSVPStatus.NOT_GOING
    assert "не участвуете" in fake_bot_api.sent_texts[-1]


async def test_deeplink_cancelled_event_registers_without_rsvp(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory, status=EventStatus.CANCELLED)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_start_update(f"alpha_{ids['event_id']}_g")),
    )

    async with session_factory() as session:
        assert (
            await session.scalar(
                select(ProjectMembership)
                .join(User, User.id == ProjectMembership.user_id)
                .where(User.tg_user_id == _USER_TG_ID)
            )
        ) is not None
    assert await _rsvp_of_new_user(session_factory, ids["event_id"]) is None

    reply = fake_bot_api.sent_texts[-1]
    assert "Вы зарегистрированы" in reply
    assert "отменено" in reply


async def test_deeplink_finalized_event_registers_without_rsvp(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory, finalized=True)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_start_update(f"alpha_{ids['event_id']}_g")),
    )

    assert await _rsvp_of_new_user(session_factory, ids["event_id"]) is None
    assert "зафиксирована" in fake_bot_api.sent_texts[-1]


async def test_deeplink_unknown_project_falls_back_to_plain_payload(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory)

    # `bogus_5_g` разбирается как RSVP-намерение, но проекта `bogus` нет —
    # откатываемся на трактовку всего аргумента как обычного invite-payload.
    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_start_update("bogus_5_g"))
    )

    async with session_factory() as session:
        assert (
            await session.scalar(select(User).where(User.tg_user_id == _USER_TG_ID))
        ) is None
    assert "недействительна" in fake_bot_api.sent_texts[-1]


async def test_plain_invite_payload_shaped_like_rsvp_still_registers(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Настоящий invite-payload, который сам по себе выглядит как RSVP-намерение.
    await _seed(session_factory, invite_payload="weird_1_n")
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_start_update("weird_1_n"))
    )

    async with session_factory() as session:
        membership = await session.scalar(
            select(ProjectMembership)
            .join(User, User.id == ProjectMembership.user_id)
            .where(User.tg_user_id == _USER_TG_ID)
        )
        assert membership is not None
    assert "Вы зарегистрированы в проекте «Alpha»" in fake_bot_api.sent_texts[-1]
