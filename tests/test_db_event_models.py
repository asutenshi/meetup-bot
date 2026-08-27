import datetime
import decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from meetup_bot.db.enums import EventStatus, RSVPStatus
from meetup_bot.db.models import Event, EventCoOrganizer, EventRSVP, Project, User

STARTS_AT = datetime.datetime(2026, 9, 1, 18, 0, tzinfo=datetime.UTC)


async def _project(session: AsyncSession) -> Project:
    project = Project(tg_chat_id=-100, name="Friends", invite_payload="friends")
    session.add(project)
    await session.flush()
    return project


async def _user(session: AsyncSession, tg_user_id: int, first_name: str = "User") -> User:
    user = User(tg_user_id=tg_user_id, first_name=first_name)
    session.add(user)
    await session.flush()
    return user


async def _event(session: AsyncSession, **overrides: object) -> Event:
    project = await _project(session)
    creator = await _user(session, tg_user_id=1, first_name="Creator")
    kwargs: dict[str, object] = {
        "project_id": project.id,
        "description": "Осенний поход",
        "starts_at": STARTS_AT,
        "location": "Лес",
        "created_by": creator.id,
    }
    kwargs.update(overrides)
    event = Event(**kwargs)
    session.add(event)
    await session.flush()
    return event


async def test_event_defaults(session: AsyncSession) -> None:
    event = await _event(session)
    await session.commit()
    await session.refresh(event)

    assert event.status is EventStatus.PLANNED
    assert event.title is None
    assert event.ends_at is None
    assert event.budget_per_person is None
    assert event.seats_limit is None
    assert event.announcement_message_id is None
    assert event.attendance_finalized_at is None
    assert event.created_at is not None
    assert event.updated_at is not None


async def test_event_full_payload_roundtrip(session: AsyncSession) -> None:
    ends_at = STARTS_AT + datetime.timedelta(days=2)
    event = await _event(
        session,
        title="Поход",
        ends_at=ends_at,
        budget_per_person=decimal.Decimal("1250.50"),
        seats_limit=8,
        status=EventStatus.COMPLETED,
        announcement_message_id=555,
    )
    await session.commit()

    stored = await session.scalar(select(Event).where(Event.id == event.id))
    assert stored is not None
    assert stored.title == "Поход"
    assert stored.ends_at == ends_at
    assert stored.budget_per_person == decimal.Decimal("1250.50")
    assert stored.seats_limit == 8
    assert stored.status is EventStatus.COMPLETED
    assert stored.announcement_message_id == 555


async def test_event_status_check_constraint_rejects_unknown_value(session: AsyncSession) -> None:
    event = await _event(session)
    await session.commit()

    with pytest.raises(IntegrityError):
        await session.execute(
            Event.__table__.update().where(Event.__table__.c.id == event.id).values(status="paused")
        )
        await session.flush()


async def test_co_organizer_unique_per_event_and_user(session: AsyncSession) -> None:
    event = await _event(session)
    member = await _user(session, tg_user_id=2, first_name="Co")
    session.add(EventCoOrganizer(event_id=event.id, user_id=member.id))
    await session.commit()

    session.add(EventCoOrganizer(event_id=event.id, user_id=member.id))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_rsvp_unique_per_event_and_user(session: AsyncSession) -> None:
    event = await _event(session)
    member = await _user(session, tg_user_id=2, first_name="Guest")
    session.add(
        EventRSVP(event_id=event.id, user_id=member.id, status=RSVPStatus.GOING)
    )
    await session.commit()

    session.add(
        EventRSVP(event_id=event.id, user_id=member.id, status=RSVPStatus.NOT_GOING)
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_rsvp_status_is_required(session: AsyncSession) -> None:
    event = await _event(session)
    member = await _user(session, tg_user_id=2, first_name="Guest")
    session.add(EventRSVP(event_id=event.id, user_id=member.id))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_rsvp_tracks_updated_by_distinct_from_user(session: AsyncSession) -> None:
    event = await _event(session)
    member = await _user(session, tg_user_id=2, first_name="Guest")
    organizer = await _user(session, tg_user_id=3, first_name="Org")
    rsvp = EventRSVP(
        event_id=event.id,
        user_id=member.id,
        status=RSVPStatus.NOT_GOING,
        updated_by=organizer.id,
    )
    session.add(rsvp)
    await session.commit()

    stored = await session.scalar(select(EventRSVP).where(EventRSVP.id == rsvp.id))
    assert stored is not None
    assert stored.user_id == member.id
    assert stored.updated_by == organizer.id
    assert stored.responded_at is not None


async def test_event_relationships_load(session: AsyncSession) -> None:
    event = await _event(session)
    co = await _user(session, tg_user_id=2, first_name="Co")
    guest = await _user(session, tg_user_id=3, first_name="Guest")
    session.add(EventCoOrganizer(event_id=event.id, user_id=co.id))
    session.add(EventRSVP(event_id=event.id, user_id=guest.id, status=RSVPStatus.GOING))
    await session.commit()

    stored = await session.scalar(
        select(Event)
        .where(Event.id == event.id)
        .options(
            selectinload(Event.co_organizers),
            selectinload(Event.rsvps),
            selectinload(Event.creator),
            selectinload(Event.project),
        )
    )
    assert stored is not None
    assert [c.user_id for c in stored.co_organizers] == [co.id]
    assert [r.user_id for r in stored.rsvps] == [guest.id]
    assert stored.creator.first_name == "Creator"
    assert stored.project.name == "Friends"
