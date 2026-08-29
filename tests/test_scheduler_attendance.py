import datetime as dt
import logging
from datetime import UTC

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.enums import EventStatus, MembershipRole, MembershipStatus, RSVPStatus
from meetup_bot.db.models import (
    Event,
    EventRSVP,
    Project,
    ProjectMembership,
    ProjectSettings,
    User,
)
from meetup_bot.scheduler.attendance import _finalization_due_at, finalize_attendance

# Начало (UTC). Полночь следующего дня в Europe/Moscow (UTC+3) — 2026-09-02
# 00:00+03:00, т.е. 2026-09-01 21:00 UTC.
STARTS_AT = dt.datetime(2026, 9, 1, 18, 0, tzinfo=UTC)
MOSCOW_DUE = dt.datetime(2026, 9, 1, 21, 0, tzinfo=UTC)

_user_ids = iter(range(1, 10_000))


async def _project(session: AsyncSession, *, timezone: str = "Europe/Moscow") -> Project:
    project = Project(
        tg_chat_id=next(_user_ids), name="Friends", invite_payload=f"inv{next(_user_ids)}"
    )
    session.add(project)
    await session.flush()
    session.add(ProjectSettings(project_id=project.id, timezone=timezone))
    await session.flush()
    return project


async def _member(
    session: AsyncSession,
    project: Project,
    *,
    status: MembershipStatus = MembershipStatus.ACTIVE,
    missed: int = 0,
    last_attended_at: dt.datetime | None = None,
) -> tuple[User, ProjectMembership]:
    user = User(tg_user_id=next(_user_ids), first_name="Member")
    session.add(user)
    await session.flush()
    membership = ProjectMembership(
        project_id=project.id,
        user_id=user.id,
        role=MembershipRole.MEMBER,
        status=status,
        consecutive_missed_events=missed,
        last_attended_at=last_attended_at,
    )
    session.add(membership)
    await session.flush()
    return user, membership


async def _event(
    session: AsyncSession,
    project: Project,
    *,
    starts_at: dt.datetime = STARTS_AT,
    ends_at: dt.datetime | None = None,
    status: EventStatus = EventStatus.PLANNED,
    finalized_at: dt.datetime | None = None,
) -> Event:
    creator = User(tg_user_id=next(_user_ids), first_name="Creator")
    session.add(creator)
    await session.flush()
    event = Event(
        project_id=project.id,
        description="Осенний поход",
        starts_at=starts_at,
        ends_at=ends_at,
        location="Лес",
        created_by=creator.id,
        status=status,
        attendance_finalized_at=finalized_at,
    )
    session.add(event)
    await session.flush()
    return event


async def _rsvp(
    session: AsyncSession, event: Event, user: User, status: RSVPStatus
) -> None:
    session.add(EventRSVP(event_id=event.id, user_id=user.id, status=status))
    await session.flush()


# --- _finalization_due_at (без БД) ----------------------------------------------


def test_due_at_is_midnight_of_next_day_in_project_tz() -> None:
    assert _finalization_due_at(STARTS_AT, "Europe/Moscow") == MOSCOW_DUE


def test_due_at_shifts_with_timezone() -> None:
    # Vladivostok — UTC+10: 2026-09-01 18:00 UTC → локально уже 2026-09-02,
    # полночь следующего дня — 2026-09-03 00:00+10:00 == 2026-09-02 14:00 UTC.
    assert _finalization_due_at(STARTS_AT, "Asia/Vladivostok") == dt.datetime(
        2026, 9, 2, 14, 0, tzinfo=UTC
    )


def test_due_at_treats_naive_end_as_utc() -> None:
    naive = STARTS_AT.replace(tzinfo=None)
    assert _finalization_due_at(naive, "Europe/Moscow") == MOSCOW_DUE


def test_due_at_falls_back_on_unknown_timezone(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="meetup_bot.scheduler")
    assert _finalization_due_at(STARTS_AT, "Mars/Olympus") == MOSCOW_DUE
    assert "неизвестная таймзона" in caplog.text


# --- finalize_attendance ------------------------------------------------------


async def test_finalizes_ripe_event(session: AsyncSession) -> None:
    project = await _project(session)
    event = await _event(session, project)
    going_user, going = await _member(session, project, missed=2)
    declined_user, declined = await _member(session, project, missed=1)
    _silent_user, silent = await _member(session, project, missed=0)
    await _rsvp(session, event, going_user, RSVPStatus.GOING)
    await _rsvp(session, event, declined_user, RSVPStatus.NOT_GOING)

    now = MOSCOW_DUE + dt.timedelta(minutes=30)
    await finalize_attendance(session, now=now)

    assert going.last_attended_at == now
    assert going.consecutive_missed_events == 0
    # not_going и не ответившие — оба «отсутствовали», счётчик растёт от прежнего.
    assert declined.consecutive_missed_events == 2
    assert declined.last_attended_at is None
    assert silent.consecutive_missed_events == 1
    assert event.attendance_finalized_at == now


async def test_skips_event_before_due_moment(session: AsyncSession) -> None:
    project = await _project(session)
    event = await _event(session, project)
    _user, membership = await _member(session, project, missed=1)

    await finalize_attendance(session, now=MOSCOW_DUE - dt.timedelta(minutes=1))

    assert event.attendance_finalized_at is None
    assert membership.consecutive_missed_events == 1


async def test_respects_project_timezone(session: AsyncSession) -> None:
    project = await _project(session, timezone="Asia/Vladivostok")
    event = await _event(session, project)
    _user, membership = await _member(session, project)

    # Для Москвы момент уже наступил, для Владивостока — ещё нет.
    await finalize_attendance(session, now=dt.datetime(2026, 9, 2, 12, 0, tzinfo=UTC))
    assert event.attendance_finalized_at is None

    await finalize_attendance(session, now=dt.datetime(2026, 9, 2, 15, 0, tzinfo=UTC))
    assert event.attendance_finalized_at is not None
    assert membership.consecutive_missed_events == 1


async def test_uses_ends_at_for_multiday_event(session: AsyncSession) -> None:
    project = await _project(session)
    ends_at = STARTS_AT + dt.timedelta(days=3)
    event = await _event(session, project, ends_at=ends_at)
    _user, membership = await _member(session, project)

    # Позже порога по starts_at, но раньше порога по ends_at — не трогаем.
    await finalize_attendance(session, now=STARTS_AT + dt.timedelta(days=1))
    assert event.attendance_finalized_at is None

    await finalize_attendance(session, now=ends_at + dt.timedelta(days=1))
    assert event.attendance_finalized_at is not None
    assert membership.consecutive_missed_events == 1


async def test_ignores_already_finalized_event(session: AsyncSession) -> None:
    project = await _project(session)
    earlier = MOSCOW_DUE - dt.timedelta(days=5)
    event = await _event(session, project, finalized_at=earlier)
    _user, membership = await _member(session, project, missed=5)

    await finalize_attendance(session, now=MOSCOW_DUE + dt.timedelta(hours=1))

    assert event.attendance_finalized_at == earlier
    assert membership.consecutive_missed_events == 5


async def test_ignores_cancelled_event(session: AsyncSession) -> None:
    project = await _project(session)
    event = await _event(session, project, status=EventStatus.CANCELLED)
    _user, membership = await _member(session, project, missed=1)

    await finalize_attendance(session, now=MOSCOW_DUE + dt.timedelta(hours=1))

    assert event.attendance_finalized_at is None
    assert membership.consecutive_missed_events == 1


async def test_ignores_removed_members(session: AsyncSession) -> None:
    project = await _project(session)
    event = await _event(session, project)
    removed_user, removed = await _member(
        session, project, status=MembershipStatus.REMOVED, missed=0
    )
    await _rsvp(session, event, removed_user, RSVPStatus.GOING)

    await finalize_attendance(session, now=MOSCOW_DUE + dt.timedelta(hours=1))

    assert removed.consecutive_missed_events == 0
    assert removed.last_attended_at is None
    assert event.attendance_finalized_at is not None


async def test_going_rsvp_from_non_member_is_harmless(session: AsyncSession) -> None:
    project = await _project(session)
    event = await _event(session, project)
    outsider = User(tg_user_id=next(_user_ids), first_name="Outsider")
    session.add(outsider)
    await session.flush()
    await _rsvp(session, event, outsider, RSVPStatus.GOING)

    await finalize_attendance(session, now=MOSCOW_DUE + dt.timedelta(hours=1))

    assert event.attendance_finalized_at is not None


async def test_logs_processed_count(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    project = await _project(session)
    await _event(session, project)
    await _member(session, project)
    caplog.set_level(logging.INFO, logger="meetup_bot.scheduler")

    await finalize_attendance(session, now=MOSCOW_DUE + dt.timedelta(hours=1))

    assert "обработано мероприятий — 1" in caplog.text
