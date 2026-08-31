import datetime

from aiogram import Bot
from aiogram.types import Update
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.bot import create_dispatcher
from meetup_bot.db.enums import EventStatus, MembershipRole, MembershipStatus, RSVPStatus
from meetup_bot.db.models import (
    Event,
    EventRSVP,
    Project,
    ProjectMembership,
    ProjectSettings,
    User,
)
from tests.conftest import FakeBotApi

_CHAT_ID = -100_500
_ANNOUNCEMENT_ID = 7777
_ANYA_TG_ID = 111
_MISHA_TG_ID = 222
_OUTSIDER_TG_ID = 999

_STARTS_AT = datetime.datetime(2026, 9, 14, 15, 0, tzinfo=datetime.UTC)


async def _seed(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    status: EventStatus = EventStatus.PLANNED,
    finalized: bool = False,
    announcement_message_id: int | None = _ANNOUNCEMENT_ID,
) -> dict[str, int]:
    async with session_factory() as session:
        project = Project(tg_chat_id=_CHAT_ID, name="Alpha", invite_payload="alpha")
        session.add(project)
        await session.flush()
        session.add(ProjectSettings(project_id=project.id, timezone="Europe/Moscow"))

        anya = User(tg_user_id=_ANYA_TG_ID, first_name="Аня", username="anya")
        misha = User(tg_user_id=_MISHA_TG_ID, first_name="Миша")
        session.add_all([anya, misha])
        await session.flush()
        session.add_all(
            [
                ProjectMembership(
                    project_id=project.id, user_id=anya.id, role=MembershipRole.OWNER
                ),
                ProjectMembership(
                    project_id=project.id, user_id=misha.id, role=MembershipRole.MEMBER
                ),
            ]
        )

        event = Event(
            project_id=project.id,
            description="Вечерняя прогулка",
            starts_at=_STARTS_AT,
            location="Парк Горького",
            status=status,
            created_by=anya.id,
            announcement_message_id=announcement_message_id,
            attendance_finalized_at=(
                datetime.datetime(2026, 9, 16, tzinfo=datetime.UTC) if finalized else None
            ),
        )
        session.add(event)
        await session.flush()
        await session.commit()

        return {
            "project_id": project.id,
            "event_id": event.id,
            "anya_id": anya.id,
            "misha_id": misha.id,
        }


def _rsvp_callback(
    event_id: int,
    status: str,
    *,
    update_id: int = 1,
    user_id: int = _ANYA_TG_ID,
    first_name: str = "Аня",
    username: str | None = "anya",
) -> dict:
    from_user: dict[str, object] = {
        "id": user_id,
        "is_bot": False,
        "first_name": first_name,
    }
    if username is not None:
        from_user["username"] = username
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cb{update_id}",
            "from": from_user,
            "message": {
                "message_id": _ANNOUNCEMENT_ID,
                "date": 1700000000,
                "chat": {"id": _CHAT_ID, "type": "supergroup", "title": "Alpha"},
                "text": "placeholder",
            },
            "chat_instance": "1",
            "data": f"rsvp:{event_id}:{status}",
        },
    }


def _member_callback(
    event_id: int, status: str, *, update_id: int = 1
) -> dict:
    """Нажатие от Миши (без username — проверяем text-mention)."""
    return _rsvp_callback(
        event_id,
        status,
        update_id=update_id,
        user_id=_MISHA_TG_ID,
        first_name="Миша",
        username=None,
    )


async def _rsvp_row(
    session_factory: async_sessionmaker[AsyncSession], ids: dict[str, int], who: str
) -> EventRSVP | None:
    async with session_factory() as session:
        return await session.scalar(
            select(EventRSVP).where(
                EventRSVP.event_id == ids["event_id"],
                EventRSVP.user_id == ids[f"{who}_id"],
            )
        )


async def test_going_click_creates_rsvp_and_updates_announcement(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_rsvp_callback(ids["event_id"], "going")),
    )

    rsvp = await _rsvp_row(session_factory, ids, "anya")
    assert rsvp is not None
    assert rsvp.status == RSVPStatus.GOING
    assert rsvp.updated_by == ids["anya_id"]

    edited = fake_bot_api.edited_messages[-1]
    assert edited.chat_id == _CHAT_ID
    assert edited.message_id == _ANNOUNCEMENT_ID
    assert "✅ Участвует: 1" in (edited.text or "")
    assert "@anya" in (edited.text or "")
    assert fake_bot_api.callback_answers[-1] == "Вы участвуете ✅"


async def test_second_click_toggles_status_off(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_rsvp_callback(ids["event_id"], "going"))
    )
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(
            _rsvp_callback(ids["event_id"], "not_going", update_id=2)
        ),
    )

    rsvp = await _rsvp_row(session_factory, ids, "anya")
    assert rsvp is not None
    assert rsvp.status == RSVPStatus.NOT_GOING

    assert "✅ Участвует: 0" in (fake_bot_api.edited_messages[-1].text or "")
    assert fake_bot_api.callback_answers[-1] == "Вы не участвуете ❌"


async def test_repeated_same_status_is_idempotent_no_extra_edit(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_rsvp_callback(ids["event_id"], "going"))
    )
    edits_after_first = len(fake_bot_api.edited_messages)

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_rsvp_callback(ids["event_id"], "going", update_id=2)),
    )

    assert len(fake_bot_api.edited_messages) == edits_after_first
    assert fake_bot_api.callback_answers[-1] == "Вы участвуете ✅"


async def test_two_members_going_are_both_listed_in_order(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(
            _member_callback(ids["event_id"], "going")
        ),
    )
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_rsvp_callback(ids["event_id"], "going", update_id=2)),
    )

    text = fake_bot_api.edited_messages[-1].text or ""
    assert "✅ Участвует: 2" in text
    misha_mention = f'<a href="tg://user?id={_MISHA_TG_ID}">Миша</a>'
    assert misha_mention in text
    assert text.index(misha_mention) < text.index("@anya")


async def test_not_going_click_shows_second_block_in_announcement(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_rsvp_callback(ids["event_id"], "going")),
    )
    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(
            _member_callback(ids["event_id"], "not_going", update_id=2)
        ),
    )

    text = fake_bot_api.edited_messages[-1].text or ""
    assert "✅ Участвует: 1" in text
    assert "@anya" in text
    assert "❌ Не участвует: 1" in text
    assert f'<a href="tg://user?id={_MISHA_TG_ID}">Миша</a>' in text
    assert text.index("❌ Не участвует") > text.index("@anya")


async def test_repeated_not_going_click_clears_rsvp(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_rsvp_callback(ids["event_id"], "not_going")),
    )
    assert (await _rsvp_row(session_factory, ids, "anya")) is not None
    assert "❌ Не участвует: 1" in (fake_bot_api.edited_messages[-1].text or "")

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(
            _rsvp_callback(ids["event_id"], "not_going", update_id=2)
        ),
    )

    # Строка снята — человек снова «ещё думает», блока «не участвует» нет.
    assert (await _rsvp_row(session_factory, ids, "anya")) is None
    text = fake_bot_api.edited_messages[-1].text or ""
    assert "Не участвует" not in text
    assert "@anya" not in text
    assert fake_bot_api.callback_answers[-1] == "Отметка снята — вы пока не ответили 🤔"


async def test_cleared_rsvp_can_be_set_again(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory)

    for update_id, status in ((1, "not_going"), (2, "not_going"), (3, "not_going")):
        await dispatcher.feed_update(
            bot=bot,
            update=Update.model_validate(
                _rsvp_callback(ids["event_id"], status, update_id=update_id)
            ),
        )

    rsvp = await _rsvp_row(session_factory, ids, "anya")
    assert rsvp is not None
    assert rsvp.status == RSVPStatus.NOT_GOING
    assert "❌ Не участвует: 1" in (fake_bot_api.edited_messages[-1].text or "")


async def test_repeated_going_click_does_not_clear_rsvp(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory)

    for update_id in (1, 2):
        await dispatcher.feed_update(
            bot=bot,
            update=Update.model_validate(
                _rsvp_callback(ids["event_id"], "going", update_id=update_id)
            ),
        )

    rsvp = await _rsvp_row(session_factory, ids, "anya")
    assert rsvp is not None
    assert rsvp.status == RSVPStatus.GOING
    assert fake_bot_api.callback_answers[-1] == "Вы участвуете ✅"


async def test_non_member_click_is_rejected(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(
            _rsvp_callback(
                ids["event_id"], "going", user_id=_OUTSIDER_TG_ID, first_name="Чужак", username=None
            )
        ),
    )

    async with session_factory() as session:
        assert list(await session.scalars(select(EventRSVP.id))) == []
    assert fake_bot_api.edited_messages == []
    assert any("зарегистрируйтесь" in a.lower() for a in fake_bot_api.callback_answers)


async def test_removed_member_click_is_rejected(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory)
    async with session_factory() as session:
        membership = await session.scalar(
            select(ProjectMembership).where(ProjectMembership.user_id == ids["misha_id"])
        )
        assert membership is not None
        membership.status = MembershipStatus.REMOVED
        await session.commit()
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(
            _member_callback(ids["event_id"], "going")
        ),
    )

    assert await _rsvp_row(session_factory, ids, "misha") is None


async def test_cancelled_event_click_is_rejected(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory, status=EventStatus.CANCELLED)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_rsvp_callback(ids["event_id"], "going"))
    )

    assert await _rsvp_row(session_factory, ids, "anya") is None
    assert any("отменено" in a.lower() for a in fake_bot_api.callback_answers)


async def test_finalized_event_click_is_rejected(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory, finalized=True)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_rsvp_callback(ids["event_id"], "going"))
    )

    assert await _rsvp_row(session_factory, ids, "anya") is None
    assert any("зафиксирова" in a.lower() for a in fake_bot_api.callback_answers)


async def test_unknown_event_click_is_rejected(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_rsvp_callback(999_999, "going"))
    )

    assert any("не найдено" in a.lower() for a in fake_bot_api.callback_answers)
    assert fake_bot_api.edited_messages == []


async def test_first_not_going_click_recorded_without_failing_on_identical_text(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot,
        update=Update.model_validate(_rsvp_callback(ids["event_id"], "not_going")),
    )

    rsvp = await _rsvp_row(session_factory, ids, "anya")
    assert rsvp is not None
    assert rsvp.status == RSVPStatus.NOT_GOING
    assert fake_bot_api.callback_answers[-1] == "Вы не участвуете ❌"


async def test_click_without_announcement_message_still_records_rsvp(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory, announcement_message_id=None)
    dispatcher = create_dispatcher(session_factory)

    await dispatcher.feed_update(
        bot=bot, update=Update.model_validate(_rsvp_callback(ids["event_id"], "going"))
    )

    rsvp = await _rsvp_row(session_factory, ids, "anya")
    assert rsvp is not None
    assert fake_bot_api.edited_messages == []
