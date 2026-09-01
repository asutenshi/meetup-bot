"""Сервисные функции постфактум-корректировки RSVP (задачи 3.1 / 3.2)."""

import datetime

from sqlalchemy import select, update
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
    is_latest_finalized_event,
    list_events_for_rsvp_correction,
    recompute_membership_attendance,
)

_NOW = datetime.datetime(2026, 9, 1, 12, 0, tzinfo=datetime.UTC)


def _dt(days: int) -> datetime.datetime:
    return _NOW + datetime.timedelta(days=days)


def _utc(value: datetime.datetime) -> datetime.datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=datetime.UTC)


async def _project(session: AsyncSession) -> tuple[int, int, int]:
    """Проект + создатель (owner) + обычный участник. Возвращает их id."""
    project = Project(tg_chat_id=-100, name="Alpha", invite_payload="alpha")
    session.add(project)
    await session.flush()
    creator = User(tg_user_id=1, first_name="Создатель")
    member = User(tg_user_id=2, first_name="Участник")
    session.add_all([creator, member])
    await session.flush()
    # Явный ранний `registered_at`: иначе server_default (сегодняшняя дата) окажется
    # позже исторических мероприятий, и пересчёт сочтёт их «до вступления».
    session.add_all(
        [
            ProjectMembership(
                project_id=project.id,
                user_id=creator.id,
                role=MembershipRole.OWNER,
                registered_at=_dt(-100),
            ),
            ProjectMembership(
                project_id=project.id,
                user_id=member.id,
                role=MembershipRole.MEMBER,
                registered_at=_dt(-100),
            ),
        ]
    )
    await session.commit()
    return project.id, creator.id, member.id


def _event(project_id: int, creator_id: int, *, starts: int, **kw: object) -> Event:
    return Event(
        project_id=project_id,
        description="встреча",
        starts_at=_dt(starts),
        location="Парк",
        created_by=creator_id,
        **kw,
    )


async def _membership(session: AsyncSession, user_id: int) -> ProjectMembership:
    membership = await session.scalar(
        select(ProjectMembership).where(ProjectMembership.user_id == user_id)
    )
    assert membership is not None
    return membership


async def test_list_for_correction_filters_cancelled_keeps_finalized(
    session: AsyncSession,
) -> None:
    project_id, creator_id, _ = await _project(session)
    live = _event(project_id, creator_id, starts=5)
    finalized = _event(
        project_id, creator_id, starts=-3, attendance_finalized_at=_dt(-2)
    )
    cancelled = _event(project_id, creator_id, starts=6, status=EventStatus.CANCELLED)
    session.add_all([live, finalized, cancelled])
    await session.commit()

    events = await list_events_for_rsvp_correction(
        session, project_id=project_id, user_id=creator_id, is_admin=True, now=_NOW
    )
    assert {e.id for e in events} == {live.id, finalized.id}


async def test_list_for_correction_orders_upcoming_then_recent_past(
    session: AsyncSession,
) -> None:
    project_id, creator_id, _ = await _project(session)
    soon = _event(project_id, creator_id, starts=2)
    later = _event(project_id, creator_id, starts=9)
    yesterday = _event(project_id, creator_id, starts=-1)
    long_ago = _event(project_id, creator_id, starts=-10)
    session.add_all([later, long_ago, soon, yesterday])
    await session.commit()

    events = await list_events_for_rsvp_correction(
        session, project_id=project_id, user_id=creator_id, is_admin=True, now=_NOW
    )
    assert [e.id for e in events] == [soon.id, later.id, yesterday.id, long_ago.id]


async def test_list_for_correction_respects_can_manage(session: AsyncSession) -> None:
    project_id, creator_id, member_id = await _project(session)
    mine = _event(project_id, creator_id, starts=3)
    theirs = _event(project_id, creator_id, starts=4)
    session.add_all([mine, theirs])
    await session.flush()
    session.add(EventCoOrganizer(event_id=mine.id, user_id=member_id))
    session.add(EventCoOrganizer(event_id=theirs.id, user_id=creator_id))
    await session.commit()

    events = await list_events_for_rsvp_correction(
        session, project_id=project_id, user_id=member_id, is_admin=False, now=_NOW
    )
    assert [e.id for e in events] == [mine.id]


async def _finalized_history(session: AsyncSession) -> tuple[int, int, list[Event]]:
    """Проект с тремя финализированными мероприятиями E1<E2<E3. Возвращает
    (project_id, member_id, [E1, E2, E3])."""
    project_id, creator_id, member_id = await _project(session)
    events = [
        _event(
            project_id, creator_id, starts=day, attendance_finalized_at=_dt(day + 1)
        )
        for day in (-30, -20, -10)
    ]
    session.add_all(events)
    await session.commit()
    return project_id, member_id, events


async def _set_rsvp(
    session: AsyncSession, event_id: int, user_id: int, status: RSVPStatus
) -> None:
    session.add(
        EventRSVP(event_id=event_id, user_id=user_id, status=status, updated_by=user_id)
    )
    await session.commit()


async def test_recompute_counts_from_last_going(session: AsyncSession) -> None:
    project_id, member_id, (e1, e2, e3) = await _finalized_history(session)
    await _set_rsvp(session, e1.id, member_id, RSVPStatus.GOING)
    await _set_rsvp(session, e2.id, member_id, RSVPStatus.GOING)
    # E3 — не ответил.

    await recompute_membership_attendance(
        session, project_id=project_id, user_id=member_id
    )
    await session.commit()

    membership = await _membership(session, member_id)
    assert membership.consecutive_missed_events == 1
    assert _utc(membership.last_attended_at) == _utc(e2.attendance_finalized_at)


async def test_recompute_resets_when_latest_becomes_going(session: AsyncSession) -> None:
    project_id, member_id, (e1, e2, e3) = await _finalized_history(session)
    await _set_rsvp(session, e1.id, member_id, RSVPStatus.GOING)
    # E2, E3 пропущены → организатор отмечает присутствие на последнем (E3).
    await _set_rsvp(session, e3.id, member_id, RSVPStatus.GOING)

    await recompute_membership_attendance(
        session, project_id=project_id, user_id=member_id
    )
    await session.commit()

    membership = await _membership(session, member_id)
    assert membership.consecutive_missed_events == 0
    assert _utc(membership.last_attended_at) == _utc(e3.attendance_finalized_at)


async def test_recompute_all_missed(session: AsyncSession) -> None:
    project_id, member_id, _ = await _finalized_history(session)

    await recompute_membership_attendance(
        session, project_id=project_id, user_id=member_id
    )
    await session.commit()

    membership = await _membership(session, member_id)
    assert membership.consecutive_missed_events == 3
    assert membership.last_attended_at is None


async def test_recompute_skips_events_before_join(session: AsyncSession) -> None:
    project_id, member_id, (e1, e2, e3) = await _finalized_history(session)
    # Участник вступил уже после финализации E1 — джоба его на E1 не считала.
    await session.execute(
        update(ProjectMembership)
        .where(ProjectMembership.user_id == member_id)
        .values(registered_at=_dt(-25))
    )
    await session.commit()
    session.expire_all()

    await recompute_membership_attendance(
        session, project_id=project_id, user_id=member_id
    )
    await session.commit()

    membership = await _membership(session, member_id)
    assert membership.consecutive_missed_events == 2
    assert membership.last_attended_at is None


async def test_is_latest_finalized_event(session: AsyncSession) -> None:
    project_id, creator_id, _ = await _project(session)
    older = _event(project_id, creator_id, starts=-9, attendance_finalized_at=_dt(-8))
    newer = _event(project_id, creator_id, starts=-4, attendance_finalized_at=_dt(-3))
    not_final = _event(project_id, creator_id, starts=-1)
    session.add_all([older, newer, not_final])
    await session.commit()

    assert await is_latest_finalized_event(session, newer) is True
    assert await is_latest_finalized_event(session, older) is False
    assert await is_latest_finalized_event(session, not_final) is False
