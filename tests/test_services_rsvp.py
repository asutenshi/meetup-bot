import datetime
from typing import Any

import pytest
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
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory)
    async with session_factory() as session:
        result = await set_rsvp(
            session,
            event_id=ids["event_id"],
            tg_user_id=_MEMBER_TG_ID,
            target=RSVPStatus.GOING,
        )
    assert result == (RsvpOutcome.GOING, True)

    async with session_factory() as session:
        going, not_going, mine = await rsvp_summary(
            session, event_id=ids["event_id"], user_id=ids["member_id"]
        )
    assert (going, not_going, mine) == (1, 0, RSVPStatus.GOING)


async def test_set_rsvp_repeat_not_going_clears(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory)
    async with session_factory() as session:
        await set_rsvp(
            session,
            event_id=ids["event_id"],
            tg_user_id=_MEMBER_TG_ID,
            target=RSVPStatus.NOT_GOING,
        )
    async with session_factory() as session:
        result = await set_rsvp(
            session,
            event_id=ids["event_id"],
            tg_user_id=_MEMBER_TG_ID,
            target=RSVPStatus.NOT_GOING,
        )
    assert result == (RsvpOutcome.CLEARED, True)

    async with session_factory() as session:
        rows = list(await session.scalars(select(EventRSVP)))
    assert rows == []


async def test_set_rsvp_repeat_same_status_not_changed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory)
    async with session_factory() as session:
        await set_rsvp(
            session,
            event_id=ids["event_id"],
            tg_user_id=_MEMBER_TG_ID,
            target=RSVPStatus.GOING,
        )
    async with session_factory() as session:
        result = await set_rsvp(
            session,
            event_id=ids["event_id"],
            tg_user_id=_MEMBER_TG_ID,
            target=RSVPStatus.GOING,
        )
    # Повторный клик по уже стоящей отметке — вызывающий не станет дёргать анонс.
    assert result == (RsvpOutcome.GOING, False)


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"status": EventStatus.CANCELLED}, "event_cancelled"),
        ({"finalized": True}, "event_finalized"),
    ],
)
async def test_set_rsvp_rejects_closed_event(
    session_factory: async_sessionmaker[AsyncSession],
    kwargs: dict[str, object],
    code: str,
) -> None:
    ids = await _seed(session_factory, **kwargs)  # type: ignore[arg-type]
    async with session_factory() as session:
        with pytest.raises(RsvpError) as exc:
            await set_rsvp(
                session,
                event_id=ids["event_id"],
                tg_user_id=_MEMBER_TG_ID,
                target=RSVPStatus.GOING,
            )
    assert exc.value.code == code


async def test_set_rsvp_rejects_non_member(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory)
    async with session_factory() as session:
        with pytest.raises(RsvpError) as exc:
            await set_rsvp(
                session,
                event_id=ids["event_id"],
                tg_user_id=_OUTSIDER_TG_ID,
                target=RSVPStatus.GOING,
            )
    assert exc.value.code == "not_registered"


async def test_set_rsvp_event_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed(session_factory)
    async with session_factory() as session:
        with pytest.raises(RsvpError) as exc:
            await set_rsvp(
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


# --- гонки при повторных кликах по RSVP (задача 5.1b) --------------------------


def _stub_first_rsvp_read_stale(session: AsyncSession) -> None:
    """Патчит `session.scalar` так, что ПЕРВОЕ чтение, вернувшее строку
    `EventRSVP`, отдаёт `None`. Этим эмулируем гонку: между нашим SELECT и
    COMMIT конкурентная корутина того же участника уже вставила свою строку, а
    мы этого «не увидели» и пойдём вставлять свою. Повторные чтения (в ветке
    восстановления после `IntegrityError`) проходят как есть."""
    real_scalar = session.scalar
    fired = False

    async def scalar_with_stale_read(stmt: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal fired
        result = await real_scalar(stmt, *args, **kwargs)
        if not fired and isinstance(result, EventRSVP):
            fired = True
            return None
        return result

    session.scalar = scalar_with_stale_read  # type: ignore[method-assign]


async def test_set_rsvp_recovers_from_insert_race(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Конкурент того же участника уже вставил строку `EventRSVP` (в БД она
    есть), но наш SELECT её «не увидел» — на INSERT ловим `IntegrityError`,
    перечитываем чужую строку и применяем свой статус как update, не роняя
    вызов в 500."""
    ids = await _seed(session_factory)
    async with session_factory() as other:
        other.add(
            EventRSVP(
                event_id=ids["event_id"],
                user_id=ids["member_id"],
                status=RSVPStatus.NOT_GOING,
                updated_by=ids["member_id"],
            )
        )
        await other.commit()

    async with session_factory() as session:
        _stub_first_rsvp_read_stale(session)
        result = await set_rsvp(
            session,
            event_id=ids["event_id"],
            tg_user_id=_MEMBER_TG_ID,
            target=RSVPStatus.GOING,
        )

    assert result == (RsvpOutcome.GOING, True)
    async with session_factory() as session:
        rows = list(await session.scalars(select(EventRSVP)))
    assert len(rows) == 1
    assert rows[0].status == RSVPStatus.GOING
    assert rows[0].updated_by == ids["member_id"]


async def test_set_rsvp_recovers_from_insert_race_same_target(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Тот же гон, но конкурент выставил ровно наш статус — восстановление
    отдаёт `changed=False`, вызывающий не станет зря перерисовывать анонс."""
    ids = await _seed(session_factory)
    async with session_factory() as other:
        other.add(
            EventRSVP(
                event_id=ids["event_id"],
                user_id=ids["member_id"],
                status=RSVPStatus.GOING,
                updated_by=ids["member_id"],
            )
        )
        await other.commit()

    async with session_factory() as session:
        _stub_first_rsvp_read_stale(session)
        result = await set_rsvp(
            session,
            event_id=ids["event_id"],
            tg_user_id=_MEMBER_TG_ID,
            target=RSVPStatus.GOING,
        )

    assert result == (RsvpOutcome.GOING, False)
    async with session_factory() as session:
        rows = list(await session.scalars(select(EventRSVP)))
    assert len(rows) == 1


async def test_set_rsvp_sequential_calls_unaffected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Регрессия: без гонки (последовательные вызовы) `changed`/`RsvpOutcome`
    прежние — обработчик `IntegrityError` в тихом пути не мешает."""
    ids = await _seed(session_factory)
    async with session_factory() as session:
        first = await set_rsvp(
            session,
            event_id=ids["event_id"],
            tg_user_id=_MEMBER_TG_ID,
            target=RSVPStatus.GOING,
        )
    async with session_factory() as session:
        second = await set_rsvp(
            session,
            event_id=ids["event_id"],
            tg_user_id=_MEMBER_TG_ID,
            target=RSVPStatus.NOT_GOING,
        )
    assert first == (RsvpOutcome.GOING, True)
    assert second == (RsvpOutcome.NOT_GOING, True)
    async with session_factory() as session:
        rows = list(await session.scalars(select(EventRSVP)))
    assert [r.status for r in rows] == [RSVPStatus.NOT_GOING]
