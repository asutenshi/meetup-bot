import datetime

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.enums import EventStatus, MembershipRole, RSVPStatus
from meetup_bot.db.models import (
    Event,
    EventCoOrganizer,
    EventRSVP,
    Project,
    ProjectMembership,
    User,
)
from meetup_bot.services.events import (
    can_manage_event,
    cancel_event,
    going_members,
    list_manageable_events,
    user_is_project_admin,
)
from tests.conftest import FakeBotApi

_START = datetime.datetime(2026, 9, 20, 15, 0, tzinfo=datetime.UTC)


async def _seed(session: AsyncSession) -> dict[str, int]:
    project = Project(tg_chat_id=-100, name="Alpha", invite_payload="alpha")
    session.add(project)
    await session.flush()

    creator = User(tg_user_id=1, first_name="Создатель")
    admin = User(tg_user_id=2, first_name="Админ")
    member = User(tg_user_id=3, first_name="Участник")
    session.add_all([creator, admin, member])
    await session.flush()
    session.add_all(
        [
            ProjectMembership(
                project_id=project.id, user_id=creator.id, role=MembershipRole.MEMBER
            ),
            ProjectMembership(
                project_id=project.id, user_id=admin.id, role=MembershipRole.ADMIN
            ),
            ProjectMembership(
                project_id=project.id, user_id=member.id, role=MembershipRole.MEMBER
            ),
        ]
    )

    event = Event(
        project_id=project.id,
        description="встреча",
        starts_at=_START,
        location="парк",
        created_by=creator.id,
    )
    session.add(event)
    await session.flush()
    await session.commit()
    return {
        "project_id": project.id,
        "event_id": event.id,
        "creator_id": creator.id,
        "admin_id": admin.id,
        "member_id": member.id,
    }


async def test_no_co_organizers_creator_and_admin_can_manage(session: AsyncSession) -> None:
    ids = await _seed(session)
    event = await session.get(Event, ids["event_id"])
    assert event is not None

    assert await can_manage_event(session, event=event, user_id=ids["creator_id"], is_admin=False)
    assert await can_manage_event(session, event=event, user_id=ids["member_id"], is_admin=True)
    assert not await can_manage_event(
        session, event=event, user_id=ids["member_id"], is_admin=False
    )


async def test_with_co_organizers_only_they_can_manage(session: AsyncSession) -> None:
    ids = await _seed(session)
    session.add(EventCoOrganizer(event_id=ids["event_id"], user_id=ids["member_id"]))
    await session.commit()
    event = await session.get(Event, ids["event_id"])
    assert event is not None

    assert await can_manage_event(session, event=event, user_id=ids["member_id"], is_admin=False)
    # Создатель снял себя с организаторов — теряет право.
    assert not await can_manage_event(
        session, event=event, user_id=ids["creator_id"], is_admin=False
    )
    # Админ, не назначенный организатором, тоже не проходит.
    assert not await can_manage_event(
        session, event=event, user_id=ids["admin_id"], is_admin=True
    )


async def test_list_manageable_events_filters_by_right_and_status(session: AsyncSession) -> None:
    ids = await _seed(session)
    session.add_all(
        [
            Event(
                project_id=ids["project_id"],
                description="отменённое",
                starts_at=_START,
                location="X",
                created_by=ids["creator_id"],
                status=EventStatus.CANCELLED,
            ),
            Event(
                project_id=ids["project_id"],
                description="финализированное",
                starts_at=_START,
                location="Y",
                created_by=ids["creator_id"],
                attendance_finalized_at=_START,
            ),
        ]
    )
    await session.commit()

    creator_events = await list_manageable_events(
        session, project_id=ids["project_id"], user_id=ids["creator_id"], is_admin=False
    )
    assert [e.id for e in creator_events] == [ids["event_id"]]

    member_events = await list_manageable_events(
        session, project_id=ids["project_id"], user_id=ids["member_id"], is_admin=False
    )
    assert member_events == []


async def test_going_members_and_admin_check(session: AsyncSession) -> None:
    ids = await _seed(session)
    session.add_all(
        [
            EventRSVP(
                event_id=ids["event_id"],
                user_id=ids["member_id"],
                status=RSVPStatus.GOING,
                updated_by=ids["member_id"],
            ),
            EventRSVP(
                event_id=ids["event_id"],
                user_id=ids["admin_id"],
                status=RSVPStatus.NOT_GOING,
                updated_by=ids["admin_id"],
            ),
        ]
    )
    await session.commit()
    event = await session.get(Event, ids["event_id"])
    assert event is not None

    going = await going_members(session, event)
    assert [u.id for u in going] == [ids["member_id"]]

    assert await user_is_project_admin(
        session, project_id=ids["project_id"], user_id=ids["admin_id"]
    )
    assert not await user_is_project_admin(
        session, project_id=ids["project_id"], user_id=ids["member_id"]
    )


async def test_cancel_event_sets_status_notifies_and_reports_missing_announcement(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    ids = await _seed(session)
    event = await session.get(Event, ids["event_id"])
    assert event is not None
    session.add(
        EventRSVP(
            event_id=event.id,
            user_id=ids["member_id"],
            status=RSVPStatus.GOING,
            updated_by=ids["member_id"],
        )
    )
    await session.commit()

    announcement_ok, notified = await cancel_event(
        bot, session, event, timezone="Europe/Moscow"
    )

    # Анонса не было (`announcement_message_id` пуст) — перерисовать нечего.
    assert announcement_ok is False
    assert notified == 1
    assert event.status == EventStatus.CANCELLED
    assert any("Мероприятие отменено" in text for text in fake_bot_api.sent_texts)
