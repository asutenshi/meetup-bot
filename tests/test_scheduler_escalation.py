import datetime as dt
import logging
from datetime import UTC

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.enums import EventStatus, MembershipRole, MembershipStatus
from meetup_bot.db.models import (
    Event,
    EventCoOrganizer,
    Project,
    ProjectMembership,
    ProjectSettings,
    User,
)
from meetup_bot.scheduler.escalation import escalate_missed_events

from .conftest import FakeBotApi

# 2026-09-01 17:30 UTC == 20:30 в Europe/Moscow (UTC+3) — дефолтный
# `reminder_send_hour = 20`.
AT_SEND_HOUR = dt.datetime(2026, 9, 1, 17, 30, tzinfo=UTC)
OFF_HOUR = dt.datetime(2026, 9, 1, 9, 0, tzinfo=UTC)  # 12:00 в Москве

_ids = iter(range(1, 100_000))


async def _project(
    session: AsyncSession,
    *,
    timezone: str = "Europe/Moscow",
    is_active: bool = True,
    send_hour: int = 20,
    escalation_count: int = 3,
    with_settings: bool = True,
) -> Project:
    project = Project(
        tg_chat_id=next(_ids),
        name="Friends",
        invite_payload=f"inv{next(_ids)}",
        is_active=is_active,
    )
    session.add(project)
    await session.flush()
    if with_settings:
        session.add(
            ProjectSettings(
                project_id=project.id,
                timezone=timezone,
                reminder_send_hour=send_hour,
                missed_events_escalation_count=escalation_count,
            )
        )
        await session.flush()
    return project


async def _user(session: AsyncSession, *, username: str | None = None) -> User:
    user = User(
        tg_user_id=next(_ids),
        first_name="Person",
        username=username,
    )
    session.add(user)
    await session.flush()
    return user


async def _member(
    session: AsyncSession,
    project: Project,
    *,
    user: User | None = None,
    role: MembershipRole = MembershipRole.MEMBER,
    status: MembershipStatus = MembershipStatus.ACTIVE,
    missed: int = 0,
    last_escalation_sent_at: dt.datetime | None = None,
) -> tuple[User, ProjectMembership]:
    user = user or await _user(session)
    membership = ProjectMembership(
        project_id=project.id,
        user_id=user.id,
        role=role,
        status=status,
        consecutive_missed_events=missed,
        last_escalation_sent_at=last_escalation_sent_at,
    )
    session.add(membership)
    await session.flush()
    return user, membership


async def _event(
    session: AsyncSession,
    project: Project,
    *,
    starts_at: dt.datetime,
    status: EventStatus = EventStatus.PLANNED,
    co_organizers: list[User] | None = None,
) -> Event:
    creator = await _user(session)
    event = Event(
        project_id=project.id,
        description="Осенний поход",
        starts_at=starts_at,
        location="Лес",
        created_by=creator.id,
        status=status,
    )
    session.add(event)
    await session.flush()
    for co in co_organizers or []:
        session.add(EventCoOrganizer(event_id=event.id, user_id=co.id))
    await session.flush()
    return event


def _texts_to(api: FakeBotApi, tg_user_id: int) -> list[str]:
    return [m.text or "" for m in api.sent_messages if m.chat_id == tg_user_id]


# --- выбор получателей -----------------------------------------------------


async def test_escalates_to_co_organizers_of_next_event(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session)
    await _member(session, project, missed=3)
    organizer = await _user(session, username="lead")
    await _member(session, project, user=organizer)
    await _event(
        session,
        project,
        starts_at=AT_SEND_HOUR + dt.timedelta(days=3),
        co_organizers=[organizer],
    )

    await escalate_missed_events(session, bot, now=AT_SEND_HOUR)

    texts = _texts_to(fake_bot_api, organizer.tg_user_id)
    assert len(texts) == 1
    assert "3 встречи" in texts[0]
    assert "@lead" not in texts[0]  # это про absent_user, не про организатора


async def test_prefers_nearest_upcoming_event(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session)
    await _member(session, project, missed=3)
    near_org = await _user(session)
    far_org = await _user(session)
    await _member(session, project, user=near_org)
    await _member(session, project, user=far_org)
    await _event(
        session,
        project,
        starts_at=AT_SEND_HOUR + dt.timedelta(days=2),
        co_organizers=[near_org],
    )
    await _event(
        session,
        project,
        starts_at=AT_SEND_HOUR + dt.timedelta(days=9),
        co_organizers=[far_org],
    )

    await escalate_missed_events(session, bot, now=AT_SEND_HOUR)

    assert len(_texts_to(fake_bot_api, near_org.tg_user_id)) == 1
    assert _texts_to(fake_bot_api, far_org.tg_user_id) == []


async def test_past_event_co_organizers_are_not_notified(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    # Будущих мероприятий нет — со-организаторы прошедшего в получатели не
    # попадают, эскалация уходит админам.
    project = await _project(session)
    await _member(session, project, missed=3)
    past_org = await _user(session)
    admin = await _user(session)
    await _member(session, project, user=past_org)
    await _member(session, project, user=admin, role=MembershipRole.ADMIN)
    await _event(
        session, project, starts_at=AT_SEND_HOUR - dt.timedelta(days=2), co_organizers=[past_org]
    )

    await escalate_missed_events(session, bot, now=AT_SEND_HOUR)

    assert _texts_to(fake_bot_api, past_org.tg_user_id) == []
    assert len(_texts_to(fake_bot_api, admin.tg_user_id)) == 1


async def test_falls_back_to_admins_without_events(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session)
    await _member(session, project, missed=3)
    owner = await _user(session)
    admin = await _user(session)
    plain = await _user(session)
    await _member(session, project, user=owner, role=MembershipRole.OWNER)
    await _member(session, project, user=admin, role=MembershipRole.ADMIN)
    await _member(session, project, user=plain, role=MembershipRole.MEMBER)

    await escalate_missed_events(session, bot, now=AT_SEND_HOUR)

    assert len(_texts_to(fake_bot_api, owner.tg_user_id)) == 1
    assert len(_texts_to(fake_bot_api, admin.tg_user_id)) == 1
    assert _texts_to(fake_bot_api, plain.tg_user_id) == []


async def test_falls_back_to_admins_when_event_has_no_co_organizers(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session)
    await _member(session, project, missed=3)
    admin = await _user(session)
    await _member(session, project, user=admin, role=MembershipRole.ADMIN)
    await _event(session, project, starts_at=AT_SEND_HOUR + dt.timedelta(days=3))

    await escalate_missed_events(session, bot, now=AT_SEND_HOUR)

    assert len(_texts_to(fake_bot_api, admin.tg_user_id)) == 1


async def test_cancelled_upcoming_event_is_ignored(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session)
    await _member(session, project, missed=3)
    cancelled_org = await _user(session)
    admin = await _user(session)
    await _member(session, project, user=cancelled_org)
    await _member(session, project, user=admin, role=MembershipRole.ADMIN)
    await _event(
        session,
        project,
        starts_at=AT_SEND_HOUR + dt.timedelta(days=1),
        status=EventStatus.CANCELLED,
        co_organizers=[cancelled_org],
    )

    await escalate_missed_events(session, bot, now=AT_SEND_HOUR)

    assert _texts_to(fake_bot_api, cancelled_org.tg_user_id) == []
    assert len(_texts_to(fake_bot_api, admin.tg_user_id)) == 1


async def test_does_not_escalate_about_member_to_themselves(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    # Пропускающий встречи участник сам является админом — эскалацию про него
    # получают только другие админы.
    project = await _project(session)
    absent_admin, _ = await _member(
        session, project, role=MembershipRole.ADMIN, missed=3
    )
    other_admin = await _user(session)
    await _member(session, project, user=other_admin, role=MembershipRole.OWNER)

    await escalate_missed_events(session, bot, now=AT_SEND_HOUR)

    assert _texts_to(fake_bot_api, absent_admin.tg_user_id) == []
    assert len(_texts_to(fake_bot_api, other_admin.tg_user_id)) == 1


# --- отбор кандидатов -----------------------------------------------------


async def test_no_op_outside_send_hour(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session)
    await _member(session, project, missed=5)
    admin = await _user(session)
    await _member(session, project, user=admin, role=MembershipRole.ADMIN)

    await escalate_missed_events(session, bot, now=OFF_HOUR)

    assert fake_bot_api.sent_messages == []


async def test_skips_members_below_threshold(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session, escalation_count=3)
    await _member(session, project, missed=2)
    admin = await _user(session)
    await _member(session, project, user=admin, role=MembershipRole.ADMIN)

    await escalate_missed_events(session, bot, now=AT_SEND_HOUR)

    assert _texts_to(fake_bot_api, admin.tg_user_id) == []


async def test_skips_removed_member(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session)
    await _member(session, project, status=MembershipStatus.REMOVED, missed=5)
    admin = await _user(session)
    await _member(session, project, user=admin, role=MembershipRole.ADMIN)

    await escalate_missed_events(session, bot, now=AT_SEND_HOUR)

    assert _texts_to(fake_bot_api, admin.tg_user_id) == []


async def test_skips_inactive_project(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session, is_active=False)
    await _member(session, project, missed=5)
    admin = await _user(session)
    await _member(session, project, user=admin, role=MembershipRole.ADMIN)

    await escalate_missed_events(session, bot, now=AT_SEND_HOUR)

    assert fake_bot_api.sent_messages == []


async def test_falls_back_to_defaults_without_settings_row(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session, with_settings=False)
    await _member(session, project, missed=3)
    admin = await _user(session)
    await _member(session, project, user=admin, role=MembershipRole.ADMIN)

    await escalate_missed_events(session, bot, now=AT_SEND_HOUR)

    assert len(_texts_to(fake_bot_api, admin.tg_user_id)) == 1


# --- троттлинг -----------------------------------------------------------


async def test_throttles_within_a_week(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session)
    _, membership = await _member(
        session,
        project,
        missed=3,
        last_escalation_sent_at=AT_SEND_HOUR - dt.timedelta(days=3),
    )
    admin = await _user(session)
    await _member(session, project, user=admin, role=MembershipRole.ADMIN)

    await escalate_missed_events(session, bot, now=AT_SEND_HOUR)

    assert _texts_to(fake_bot_api, admin.tg_user_id) == []
    assert membership.last_escalation_sent_at == AT_SEND_HOUR - dt.timedelta(days=3)


async def test_escalates_again_after_a_week(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session)
    _, membership = await _member(
        session,
        project,
        missed=3,
        last_escalation_sent_at=AT_SEND_HOUR - dt.timedelta(days=7),
    )
    admin = await _user(session)
    await _member(session, project, user=admin, role=MembershipRole.ADMIN)

    await escalate_missed_events(session, bot, now=AT_SEND_HOUR)

    assert len(_texts_to(fake_bot_api, admin.tg_user_id)) == 1
    assert membership.last_escalation_sent_at == AT_SEND_HOUR


# --- деградация ---------------------------------------------------------


async def test_delivery_failure_to_one_recipient_does_not_block_others(
    session: AsyncSession,
    bot: Bot,
    fake_bot_api: FakeBotApi,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project = await _project(session)
    _, membership = await _member(session, project, missed=3)
    blocked_admin = await _user(session)
    ok_admin = await _user(session)
    await _member(session, project, user=blocked_admin, role=MembershipRole.ADMIN)
    await _member(session, project, user=ok_admin, role=MembershipRole.ADMIN)

    real_send = bot.send_message

    async def _maybe_blocked(**kwargs: object):  # type: ignore[no-untyped-def]
        if kwargs.get("chat_id") == blocked_admin.tg_user_id:
            raise TelegramForbiddenError(
                method=SendMessage(chat_id=0, text=""), message="bot was blocked"
            )
        return await real_send(**kwargs)

    monkeypatch.setattr(bot, "send_message", _maybe_blocked)
    caplog.set_level(logging.WARNING, logger="meetup_bot.scheduler")

    await escalate_missed_events(session, bot, now=AT_SEND_HOUR)

    assert len(_texts_to(fake_bot_api, ok_admin.tg_user_id)) == 1
    assert membership.last_escalation_sent_at == AT_SEND_HOUR
    assert "не доставлено" in caplog.text


async def test_runs_without_bot(session: AsyncSession) -> None:
    project = await _project(session)
    _, membership = await _member(session, project, missed=3)
    admin = await _user(session)
    await _member(session, project, user=admin, role=MembershipRole.ADMIN)

    await escalate_missed_events(session, None, now=AT_SEND_HOUR)

    assert membership.last_escalation_sent_at == AT_SEND_HOUR


async def test_no_recipients_leaves_membership_unmarked(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi, caplog: pytest.LogCaptureFixture
) -> None:
    # Крайний случай: единственный «админ» — сам прогульщик, других получателей нет.
    project = await _project(session)
    _, membership = await _member(
        session, project, role=MembershipRole.OWNER, missed=3
    )
    caplog.set_level(logging.WARNING, logger="meetup_bot.scheduler")

    await escalate_missed_events(session, bot, now=AT_SEND_HOUR)

    # получателей нет → шаг ничего не шлёт и не ставит троттлинг (следующий
    # проход подхватит, когда в проект добавят второго админа)
    assert fake_bot_api.sent_messages == []
    assert membership.last_escalation_sent_at is None
    assert "некому отправить" in caplog.text


async def test_missed_events_word_pluralization(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session, escalation_count=1)
    await _member(session, project, missed=1)
    admin = await _user(session)
    await _member(session, project, user=admin, role=MembershipRole.ADMIN)

    await escalate_missed_events(session, bot, now=AT_SEND_HOUR)

    (text,) = _texts_to(fake_bot_api, admin.tg_user_id)
    assert "1 встречу" in text


async def test_logs_sent_count(
    session: AsyncSession, bot: Bot, caplog: pytest.LogCaptureFixture
) -> None:
    project = await _project(session)
    await _member(session, project, missed=3)
    admin = await _user(session)
    await _member(session, project, user=admin, role=MembershipRole.ADMIN)
    caplog.set_level(logging.INFO, logger="meetup_bot.scheduler")

    await escalate_missed_events(session, bot, now=AT_SEND_HOUR)

    assert "отправлено уведомлений — 1" in caplog.text
