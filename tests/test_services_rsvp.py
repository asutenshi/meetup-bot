import datetime

import pytest
from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meetup_bot.db.enums import EventStatus, MembershipRole, RSVPStatus
from meetup_bot.db.models import (
    Event,
    EventRSVP,
    Project,
    ProjectMembership,
    ProjectSettings,
    User,
)
from meetup_bot.services.rsvp import (
    RsvpError,
    RsvpOutcome,
    build_rsvp_start_payload,
    parse_rsvp_start_payload,
    rsvp_summary,
    set_rsvp,
)

_MEMBER_TG_ID = 222
_OUTSIDER_TG_ID = 999
_STARTS_AT = datetime.datetime(2026, 9, 14, 15, 0, tzinfo=datetime.UTC)


async def _seed(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    status: EventStatus = EventStatus.PLANNED,
    finalized: bool = False,
) -> dict[str, int]:
    async with session_factory() as session:
        project = Project(tg_chat_id=-100_500, name="Alpha", invite_payload="alpha")
        session.add(project)
        await session.flush()
        session.add(ProjectSettings(project_id=project.id, timezone="Europe/Moscow"))

        member = User(tg_user_id=_MEMBER_TG_ID, first_name="Миша")
        session.add(member)
        await session.flush()
        session.add(
            ProjectMembership(
                project_id=project.id, user_id=member.id, role=MembershipRole.MEMBER
            )
        )

        event = Event(
            project_id=project.id,
            description="Прогулка",
            starts_at=_STARTS_AT,
            location="Парк",
            status=status,
            created_by=member.id,
            attendance_finalized_at=(
                datetime.datetime(2026, 9, 16, tzinfo=datetime.UTC) if finalized else None
            ),
        )
        session.add(event)
        await session.flush()
        await session.commit()
        return {"event_id": event.id, "member_id": member.id}


async def test_set_rsvp_going_then_summary(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    async with session_factory() as session:
        outcome = await set_rsvp(
            bot,
            session,
            event_id=ids["event_id"],
            tg_user_id=_MEMBER_TG_ID,
            target=RSVPStatus.GOING,
        )
    assert outcome is RsvpOutcome.GOING

    async with session_factory() as session:
        going, not_going, mine = await rsvp_summary(
            session, event_id=ids["event_id"], user_id=ids["member_id"]
        )
    assert (going, not_going, mine) == (1, 0, RSVPStatus.GOING)


async def test_set_rsvp_repeat_not_going_clears(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    async with session_factory() as session:
        await set_rsvp(
            bot,
            session,
            event_id=ids["event_id"],
            tg_user_id=_MEMBER_TG_ID,
            target=RSVPStatus.NOT_GOING,
        )
    async with session_factory() as session:
        outcome = await set_rsvp(
            bot,
            session,
            event_id=ids["event_id"],
            tg_user_id=_MEMBER_TG_ID,
            target=RSVPStatus.NOT_GOING,
        )
    assert outcome is RsvpOutcome.CLEARED

    async with session_factory() as session:
        rows = list(await session.scalars(select(EventRSVP)))
    assert rows == []


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"status": EventStatus.CANCELLED}, "event_cancelled"),
        ({"finalized": True}, "event_finalized"),
    ],
)
async def test_set_rsvp_rejects_closed_event(
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
    kwargs: dict[str, object],
    code: str,
) -> None:
    ids = await _seed(session_factory, **kwargs)  # type: ignore[arg-type]
    async with session_factory() as session:
        with pytest.raises(RsvpError) as exc:
            await set_rsvp(
                bot,
                session,
                event_id=ids["event_id"],
                tg_user_id=_MEMBER_TG_ID,
                target=RSVPStatus.GOING,
            )
    assert exc.value.code == code


async def test_set_rsvp_rejects_non_member(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    ids = await _seed(session_factory)
    async with session_factory() as session:
        with pytest.raises(RsvpError) as exc:
            await set_rsvp(
                bot,
                session,
                event_id=ids["event_id"],
                tg_user_id=_OUTSIDER_TG_ID,
                target=RSVPStatus.GOING,
            )
    assert exc.value.code == "not_registered"


async def test_set_rsvp_event_not_found(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot
) -> None:
    await _seed(session_factory)
    async with session_factory() as session:
        with pytest.raises(RsvpError) as exc:
            await set_rsvp(
                bot,
                session,
                event_id=987654,
                tg_user_id=_MEMBER_TG_ID,
                target=RSVPStatus.GOING,
            )
    assert exc.value.code == "event_not_found"


@pytest.mark.parametrize(
    "invite_payload",
    ["alpha", "tok_en-with_both", "-_-_-", "endswithunderscore_"],
)
@pytest.mark.parametrize("target", [RSVPStatus.GOING, RSVPStatus.NOT_GOING])
def test_rsvp_start_payload_round_trip(
    invite_payload: str, target: RSVPStatus
) -> None:
    payload = build_rsvp_start_payload(
        invite_payload=invite_payload, event_id=42, target=target
    )
    assert parse_rsvp_start_payload(payload) == (invite_payload, 42, target)


@pytest.mark.parametrize(
    "payload",
    [
        "plain-invite-payload",
        "no_number_g",
        "alpha_12_x",
        "alpha_12",
        "_12_g",
        "alpha_-1_g",
    ],
)
def test_parse_rsvp_start_payload_rejects_non_matching(payload: str) -> None:
    assert parse_rsvp_start_payload(payload) is None
