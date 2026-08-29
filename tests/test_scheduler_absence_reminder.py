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
    Project,
    ProjectMembership,
    ProjectSettings,
    User,
)
from meetup_bot.scheduler.absence_reminder import remind_absent_members

from .conftest import FakeBotApi

# 2026-09-01 17:30 UTC == 20:30 в Europe/Moscow (UTC+3) — попадает в дефолтный
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
    days_threshold: int = 14,
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
                reminder_days_threshold=days_threshold,
                missed_events_escalation_count=escalation_count,
            )
        )
        await session.flush()
    return project


async def _member(
    session: AsyncSession,
    project: Project,
    *,
    status: MembershipStatus = MembershipStatus.ACTIVE,
    missed: int = 0,
    last_attended_at: dt.datetime | None = None,
    registered_at: dt.datetime | None = None,
    last_reminder_sent_at: dt.datetime | None = None,
    tg_user_id: int | None = None,
) -> tuple[User, ProjectMembership]:
    user = User(tg_user_id=tg_user_id or next(_ids), first_name="Member")
    session.add(user)
    await session.flush()
    membership = ProjectMembership(
        project_id=project.id,
        user_id=user.id,
        role=MembershipRole.MEMBER,
        status=status,
        consecutive_missed_events=missed,
        last_attended_at=last_attended_at,
        registered_at=registered_at or (AT_SEND_HOUR - dt.timedelta(days=365)),
        last_reminder_sent_at=last_reminder_sent_at,
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
    title: str | None = None,
) -> Event:
    creator = User(tg_user_id=next(_ids), first_name="Creator")
    session.add(creator)
    await session.flush()
    event = Event(
        project_id=project.id,
        title=title,
        description="Осенний поход",
        starts_at=starts_at,
        location="Лес",
        created_by=creator.id,
        status=status,
    )
    session.add(event)
    await session.flush()
    return event


def _texts_to(api: FakeBotApi, tg_user_id: int) -> list[str]:
    return [m.text or "" for m in api.sent_messages if m.chat_id == tg_user_id]


# --- рассылка ---------------------------------------------------------------


async def test_reminds_long_absent_member(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session)
    user, membership = await _member(
        session, project, last_attended_at=AT_SEND_HOUR - dt.timedelta(days=20)
    )

    await remind_absent_members(session, bot, now=AT_SEND_HOUR)

    texts = _texts_to(fake_bot_api, user.tg_user_id)
    assert len(texts) == 1
    assert "20 дней" in texts[0]
    assert membership.last_reminder_sent_at == AT_SEND_HOUR


async def test_no_op_outside_send_hour(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session)
    user, membership = await _member(
        session, project, last_attended_at=AT_SEND_HOUR - dt.timedelta(days=20)
    )

    await remind_absent_members(session, bot, now=OFF_HOUR)

    assert _texts_to(fake_bot_api, user.tg_user_id) == []
    assert membership.last_reminder_sent_at is None


async def test_send_hour_is_per_project_timezone(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    # В момент AT_SEND_HOUR в Москве 20:30, а во Владивостоке (UTC+10) — 03:30.
    project = await _project(session, timezone="Asia/Vladivostok")
    user, _ = await _member(
        session, project, last_attended_at=AT_SEND_HOUR - dt.timedelta(days=20)
    )

    await remind_absent_members(session, bot, now=AT_SEND_HOUR)
    assert _texts_to(fake_bot_api, user.tg_user_id) == []

    # 2026-09-01 10:30 UTC == 20:30 во Владивостоке.
    await remind_absent_members(
        session, bot, now=dt.datetime(2026, 9, 1, 10, 30, tzinfo=UTC)
    )
    assert len(_texts_to(fake_bot_api, user.tg_user_id)) == 1


async def test_custom_send_hour(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session, send_hour=12)
    user, _ = await _member(
        session, project, last_attended_at=AT_SEND_HOUR - dt.timedelta(days=20)
    )

    await remind_absent_members(session, bot, now=OFF_HOUR)  # 12:00 в Москве

    assert len(_texts_to(fake_bot_api, user.tg_user_id)) == 1


# --- отбор кандидатов ------------------------------------------------------


async def test_skips_recently_attended(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session)
    user, _ = await _member(
        session, project, last_attended_at=AT_SEND_HOUR - dt.timedelta(days=10)
    )

    await remind_absent_members(session, bot, now=AT_SEND_HOUR)

    assert _texts_to(fake_bot_api, user.tg_user_id) == []


async def test_uses_registered_at_when_never_attended(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session)
    fresh_user, _ = await _member(
        session,
        project,
        last_attended_at=None,
        registered_at=AT_SEND_HOUR - dt.timedelta(days=5),
    )
    stale_user, _ = await _member(
        session,
        project,
        last_attended_at=None,
        registered_at=AT_SEND_HOUR - dt.timedelta(days=30),
    )

    await remind_absent_members(session, bot, now=AT_SEND_HOUR)

    assert _texts_to(fake_bot_api, fresh_user.tg_user_id) == []
    assert len(_texts_to(fake_bot_api, stale_user.tg_user_id)) == 1


async def test_skips_members_at_escalation_threshold(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session, escalation_count=3)
    escalated_user, _ = await _member(
        session,
        project,
        missed=3,
        last_attended_at=AT_SEND_HOUR - dt.timedelta(days=40),
    )
    still_reminded_user, _ = await _member(
        session,
        project,
        missed=2,
        last_attended_at=AT_SEND_HOUR - dt.timedelta(days=40),
    )

    await remind_absent_members(session, bot, now=AT_SEND_HOUR)

    assert _texts_to(fake_bot_api, escalated_user.tg_user_id) == []
    assert len(_texts_to(fake_bot_api, still_reminded_user.tg_user_id)) == 1


async def test_skips_removed_members(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session)
    user, _ = await _member(
        session,
        project,
        status=MembershipStatus.REMOVED,
        last_attended_at=AT_SEND_HOUR - dt.timedelta(days=40),
    )

    await remind_absent_members(session, bot, now=AT_SEND_HOUR)

    assert _texts_to(fake_bot_api, user.tg_user_id) == []


async def test_skips_inactive_project(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session, is_active=False)
    user, _ = await _member(
        session, project, last_attended_at=AT_SEND_HOUR - dt.timedelta(days=40)
    )

    await remind_absent_members(session, bot, now=AT_SEND_HOUR)

    assert _texts_to(fake_bot_api, user.tg_user_id) == []


async def test_falls_back_to_defaults_without_settings_row(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session, with_settings=False)
    user, _ = await _member(
        session, project, last_attended_at=AT_SEND_HOUR - dt.timedelta(days=20)
    )

    await remind_absent_members(session, bot, now=AT_SEND_HOUR)

    assert len(_texts_to(fake_bot_api, user.tg_user_id)) == 1


# --- троттлинг ------------------------------------------------------------


async def test_throttles_within_a_day(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session)
    user, membership = await _member(
        session,
        project,
        last_attended_at=AT_SEND_HOUR - dt.timedelta(days=20),
        last_reminder_sent_at=AT_SEND_HOUR - dt.timedelta(hours=2),
    )

    await remind_absent_members(session, bot, now=AT_SEND_HOUR)

    assert _texts_to(fake_bot_api, user.tg_user_id) == []
    assert membership.last_reminder_sent_at == AT_SEND_HOUR - dt.timedelta(hours=2)


async def test_reminds_again_next_day(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session)
    user, membership = await _member(
        session,
        project,
        last_attended_at=AT_SEND_HOUR - dt.timedelta(days=20),
        last_reminder_sent_at=AT_SEND_HOUR - dt.timedelta(days=1),
    )

    await remind_absent_members(session, bot, now=AT_SEND_HOUR)

    assert len(_texts_to(fake_bot_api, user.tg_user_id)) == 1
    assert membership.last_reminder_sent_at == AT_SEND_HOUR


# --- ближайшее мероприятие в тексте -------------------------------------


async def test_includes_next_planned_event(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session)
    user, _ = await _member(
        session, project, last_attended_at=AT_SEND_HOUR - dt.timedelta(days=20)
    )
    await _event(
        session,
        project,
        starts_at=AT_SEND_HOUR + dt.timedelta(days=2),
        title="Поход на Эльбрус",
    )
    # более поздний и отменённый — не должны победить
    await _event(session, project, starts_at=AT_SEND_HOUR + dt.timedelta(days=9))
    await _event(
        session,
        project,
        starts_at=AT_SEND_HOUR + dt.timedelta(hours=1),
        status=EventStatus.CANCELLED,
        title="Отменённая",
    )

    await remind_absent_members(session, bot, now=AT_SEND_HOUR)

    (text,) = _texts_to(fake_bot_api, user.tg_user_id)
    assert "Поход на Эльбрус" in text
    assert "Отменённая" not in text


async def test_ignores_past_events_for_next_event_hint(
    session: AsyncSession, bot: Bot, fake_bot_api: FakeBotApi
) -> None:
    project = await _project(session)
    user, _ = await _member(
        session, project, last_attended_at=AT_SEND_HOUR - dt.timedelta(days=20)
    )
    await _event(
        session,
        project,
        starts_at=AT_SEND_HOUR - dt.timedelta(days=1),
        title="Уже прошло",
    )

    await remind_absent_members(session, bot, now=AT_SEND_HOUR)

    (text,) = _texts_to(fake_bot_api, user.tg_user_id)
    assert "Уже прошло" not in text


# --- деградация ---------------------------------------------------------


async def test_marks_attempt_even_when_delivery_forbidden(
    session: AsyncSession,
    bot: Bot,
    fake_bot_api: FakeBotApi,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project = await _project(session)
    _blocked_user, blocked = await _member(
        session, project, last_attended_at=AT_SEND_HOUR - dt.timedelta(days=20)
    )
    ok_user, ok = await _member(
        session, project, last_attended_at=AT_SEND_HOUR - dt.timedelta(days=20)
    )

    calls = 0
    real_send = bot.send_message

    async def _maybe_blocked(**kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TelegramForbiddenError(
                method=SendMessage(chat_id=0, text=""), message="bot was blocked"
            )
        return await real_send(**kwargs)

    monkeypatch.setattr(bot, "send_message", _maybe_blocked)
    caplog.set_level(logging.WARNING, logger="meetup_bot.scheduler")

    await remind_absent_members(session, bot, now=AT_SEND_HOUR)

    # первый упал, второй доставлен — оба помечены как «попытка была»
    assert blocked.last_reminder_sent_at == AT_SEND_HOUR
    assert ok.last_reminder_sent_at == AT_SEND_HOUR
    assert len(_texts_to(fake_bot_api, ok_user.tg_user_id)) == 1
    assert "не доставлено" in caplog.text


async def test_runs_without_bot(session: AsyncSession) -> None:
    project = await _project(session)
    _user, membership = await _member(
        session, project, last_attended_at=AT_SEND_HOUR - dt.timedelta(days=20)
    )

    await remind_absent_members(session, None, now=AT_SEND_HOUR)

    assert membership.last_reminder_sent_at == AT_SEND_HOUR


async def test_logs_sent_count(
    session: AsyncSession, bot: Bot, caplog: pytest.LogCaptureFixture
) -> None:
    project = await _project(session)
    await _member(
        session, project, last_attended_at=AT_SEND_HOUR - dt.timedelta(days=20)
    )
    caplog.set_level(logging.INFO, logger="meetup_bot.scheduler")

    await remind_absent_members(session, bot, now=AT_SEND_HOUR)

    assert "разослано — 1" in caplog.text
