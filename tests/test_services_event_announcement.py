import datetime
import decimal

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
from meetup_bot.services.event_announcement import (
    EventSnapshot,
    announcement_deep_link,
    build_announcement_text,
    build_event_cancelled_notification,
    build_event_update_keyboard,
    build_event_update_notification,
    build_rsvp_keyboard,
    refresh_event_announcement,
    refresh_member_announcements,
    rsvp_callback_data,
)
from tests.conftest import FakeBotApi

STARTS_AT = datetime.datetime(2026, 9, 14, 15, 0, tzinfo=datetime.UTC)


def _event(**overrides: object) -> Event:
    kwargs: dict[str, object] = {
        "id": 7,
        "project_id": 1,
        "description": "Вечерняя прогулка",
        "starts_at": STARTS_AT,
        "location": "Парк Горького",
    }
    kwargs.update(overrides)
    return Event(**kwargs)


def _user(tg_user_id: int, first_name: str, username: str | None = None) -> User:
    return User(tg_user_id=tg_user_id, first_name=first_name, username=username)


def test_announcement_lists_time_place_description_and_zero_counter() -> None:
    text = build_announcement_text(
        _event(), co_organizers=[], going=[], timezone="Europe/Moscow"
    )

    # 15:00 UTC → 18:00 Москвы.
    assert "14 сентября, 18:00" in text
    assert "📍 Парк Горького" in text
    assert "Вечерняя прогулка" in text
    assert "✅ Участвует: 0" in text


def test_announcement_renders_optional_fields_and_end_date() -> None:
    text = build_announcement_text(
        _event(
            title="Поход",
            ends_at=STARTS_AT + datetime.timedelta(days=1),
            budget_per_person=decimal.Decimal("1250.00"),
            seats_limit=8,
        ),
        co_organizers=[],
        going=[],
        timezone="Europe/Moscow",
    )

    assert "<b>Поход</b>" in text
    assert "15 сентября, 18:00" in text
    assert "Бюджет с человека: 1250 ₽" in text
    assert "🎟 Мест: 8" in text
    assert "✅ Участвует: 0/8" in text


def test_announcement_omits_optional_fields_when_absent() -> None:
    text = build_announcement_text(
        _event(), co_organizers=[], going=[], timezone="Europe/Moscow"
    )

    assert "Бюджет" not in text
    assert "Мест" not in text
    assert "Организуют" not in text


def test_announcement_counter_and_going_mentions() -> None:
    going = [_user(10, "Аня", "anya"), _user(20, "Миша")]
    text = build_announcement_text(
        _event(), co_organizers=[_user(30, "Лера", "lera")], going=going, timezone="Europe/Moscow"
    )

    assert "Организуют: @lera" in text
    assert "✅ Участвует: 2" in text
    assert "@anya" in text
    # text-mention для скрывшего юзернейм
    assert '<a href="tg://user?id=20">Аня</a>' not in text
    assert '<a href="tg://user?id=20">Миша</a>' in text


def test_announcement_numbers_the_going_list() -> None:
    going = [_user(10, "Аня", "anya"), _user(20, "Миша"), _user(30, "Лера", "lera")]
    text = build_announcement_text(
        _event(), co_organizers=[], going=going, timezone="Europe/Moscow"
    )

    lines = text.splitlines()
    assert "1. @anya" in lines
    assert '2. <a href="tg://user?id=20">Миша</a>' in lines
    assert "3. @lera" in lines


def test_announcement_escapes_html_in_free_text() -> None:
    text = build_announcement_text(
        _event(description="<b>hack</b> & <script>"),
        co_organizers=[],
        going=[],
        timezone="Europe/Moscow",
    )

    assert "<script>" not in text
    assert "&lt;script&gt;" in text


def test_announcement_falls_back_to_utc_on_bad_timezone() -> None:
    text = build_announcement_text(
        _event(), co_organizers=[], going=[], timezone="Not/AZone"
    )

    assert "14 сентября, 15:00" in text


def test_announcement_marks_cancelled_at_the_bottom_and_drops_going_block() -> None:
    text = build_announcement_text(
        _event(status=EventStatus.CANCELLED),
        co_organizers=[],
        going=[_user(1, "Аня", "anya")],
        timezone="Europe/Moscow",
    )

    assert text.rstrip().endswith("🚫 <b>Мероприятие отменено</b>")
    assert "14 сентября, 18:00" in text
    assert "📍 Парк Горького" in text
    assert "✅ Участвует" not in text
    assert "@anya" not in text


def test_cancelled_notification_names_time_and_place() -> None:
    text = build_event_cancelled_notification(
        _event(title="Прогулка"), timezone="Europe/Moscow"
    )

    assert text.startswith("🚫 <b>Мероприятие отменено</b>")
    assert "«Прогулка» не состоится." in text
    assert "приходить не нужно" in text
    assert "🗓 14 сентября, 18:00" in text
    assert "📍 Парк Горького" in text


def test_cancelled_notification_without_title() -> None:
    text = build_event_cancelled_notification(_event(), timezone="Europe/Moscow")

    assert "Мероприятие не состоится." in text
    assert "«" not in text.split("\n")[2]


def test_cancelled_notification_shows_end_date() -> None:
    text = build_event_cancelled_notification(
        _event(ends_at=STARTS_AT + datetime.timedelta(days=1)),
        timezone="Europe/Moscow",
    )

    assert "🗓 14 сентября, 18:00 — 15 сентября, 18:00" in text


def _snapshot(**overrides: object) -> EventSnapshot:
    return EventSnapshot(_event(**overrides))


def test_update_notification_none_when_nothing_changed() -> None:
    event = _event(location="Парк Горького")
    assert (
        build_event_update_notification(
            EventSnapshot(event), event, timezone="Europe/Moscow"
        )
        is None
    )


def test_update_notification_time_shift_is_flagged_with_before_after() -> None:
    before = _snapshot()
    event = _event(title="Прогулка", starts_at=STARTS_AT + datetime.timedelta(days=2))

    text = build_event_update_notification(before, event, timezone="Europe/Moscow")

    assert text is not None
    assert text.startswith("⚠️ <b>Перенос: «Прогулка»</b>")
    assert "🗓 Новое время: <b>16 сентября, 18:00</b>" in text
    assert "Было: <s>14 сентября, 18:00</s>" in text
    assert "нажмите «Не участвую»" in text


def test_update_notification_location_change_shows_old_and_new() -> None:
    before = _snapshot(location="Парк Горького")
    event = _event(title="Прогулка", location="Кафе «Циферблат»")

    text = build_event_update_notification(before, event, timezone="Europe/Moscow")

    assert text is not None
    assert text.startswith("📍 <b>Сменилось место: «Прогулка»</b>")
    assert "📍 Теперь: <b>Кафе «Циферблат»</b>" in text
    assert "Было: <s>Парк Горького</s>" in text


def test_update_notification_minor_edits_use_soft_header_and_footer() -> None:
    before = _snapshot(budget_per_person=None, seats_limit=None)
    event = _event(
        description="Другое описание",
        budget_per_person=decimal.Decimal("800"),
        seats_limit=12,
    )

    text = build_event_update_notification(before, event, timezone="Europe/Moscow")

    assert text is not None
    assert text.startswith("✏️ <b>Обновили детали: мероприятие</b>")
    assert "📝 Поправили описание — посмотрите в анонсе" in text
    assert "Другое описание" not in text
    assert "💰 Бюджет с человека: 800 ₽ (раньше не указан)" in text
    assert "🎟 Мест: 12 (лимит добавили)" in text
    assert "действий не требуется" in text


def test_update_notification_budget_and_seats_removed() -> None:
    before = _snapshot(
        budget_per_person=decimal.Decimal("1000"), seats_limit=8
    )
    event = _event(budget_per_person=None, seats_limit=None)

    text = build_event_update_notification(before, event, timezone="Europe/Moscow")

    assert text is not None
    assert "💰 Бюджет с человека больше не указан" in text
    assert "🎟 Лимит мест снят" in text


def test_update_notification_escapes_html_in_location() -> None:
    before = _snapshot(location="Парк")
    event = _event(location="<b>Бар</b>")

    text = build_event_update_notification(before, event, timezone="Europe/Moscow")

    assert text is not None
    assert "<b>Бар</b>" not in text
    assert "&lt;b&gt;Бар&lt;/b&gt;" in text


def test_update_keyboard_has_announcement_link_and_rsvp_buttons() -> None:
    keyboard = build_event_update_keyboard(
        42, announcement_url="https://t.me/c/700/500"
    )
    rows = keyboard.inline_keyboard

    assert rows[0][0].text == "🔗 Перейти к анонсу"
    assert rows[0][0].url == "https://t.me/c/700/500"
    assert [b.callback_data for b in rows[1]] == [
        rsvp_callback_data(42, RSVPStatus.GOING),
        rsvp_callback_data(42, RSVPStatus.NOT_GOING),
    ]


def test_update_keyboard_drops_link_when_no_announcement() -> None:
    keyboard = build_event_update_keyboard(42, announcement_url=None)

    assert len(keyboard.inline_keyboard) == 1
    assert all(b.url is None for b in keyboard.inline_keyboard[0])


def test_announcement_deep_link_builds_supergroup_url() -> None:
    assert (
        announcement_deep_link(-100_1234567890, 55)
        == "https://t.me/c/1234567890/55"
    )


def test_announcement_deep_link_none_without_message_or_supergroup() -> None:
    assert announcement_deep_link(-100_1234567890, None) is None
    assert announcement_deep_link(123456, 55) is None


def test_rsvp_keyboard_callback_data() -> None:
    keyboard = build_rsvp_keyboard(42)
    datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]

    assert datas == [
        rsvp_callback_data(42, RSVPStatus.GOING),
        rsvp_callback_data(42, RSVPStatus.NOT_GOING),
    ]
    assert datas == ["rsvp:42:going", "rsvp:42:not_going"]


async def _seed_event(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    announcement_message_id: int | None = 500,
    status: EventStatus = EventStatus.PLANNED,
    finalized: bool = False,
) -> dict[str, int]:
    """Проект с двумя участниками (Аня, Миша), оба со `status=going`."""
    async with session_factory() as session:
        project = Project(tg_chat_id=-100_700, name="Alpha", invite_payload="alpha")
        session.add(project)
        await session.flush()
        session.add(ProjectSettings(project_id=project.id, timezone="Europe/Moscow"))

        anya = User(tg_user_id=1, first_name="Аня", username="anya")
        misha = User(tg_user_id=2, first_name="Миша", username="misha")
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
            description="Прогулка",
            starts_at=STARTS_AT,
            location="Парк",
            status=status,
            created_by=anya.id,
            announcement_message_id=announcement_message_id,
            attendance_finalized_at=(
                datetime.datetime(2026, 9, 20, tzinfo=datetime.UTC) if finalized else None
            ),
        )
        session.add(event)
        await session.flush()
        session.add_all(
            [
                EventRSVP(
                    event_id=event.id,
                    user_id=anya.id,
                    status=RSVPStatus.GOING,
                    updated_by=anya.id,
                ),
                EventRSVP(
                    event_id=event.id,
                    user_id=misha.id,
                    status=RSVPStatus.GOING,
                    updated_by=misha.id,
                ),
            ]
        )
        await session.commit()
        return {
            "project_id": project.id,
            "event_id": event.id,
            "anya_id": anya.id,
            "misha_id": misha.id,
            "chat_id": project.tg_chat_id,
        }


async def test_refresh_event_announcement_excludes_removed_member(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed_event(session_factory)

    async with session_factory() as session:
        membership = await session.scalar(
            select(ProjectMembership).where(ProjectMembership.user_id == ids["misha_id"])
        )
        assert membership is not None
        membership.status = MembershipStatus.REMOVED
        await session.commit()

        event = await session.get(Event, ids["event_id"])
        assert event is not None
        await refresh_event_announcement(bot, session, event)

    text = fake_bot_api.edited_messages[-1].text or ""
    assert "✅ Участвует: 1" in text
    assert "@anya" in text
    assert "@misha" not in text


async def test_refresh_event_announcement_removes_keyboard_when_cancelled(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed_event(session_factory, status=EventStatus.CANCELLED)

    async with session_factory() as session:
        event = await session.get(Event, ids["event_id"])
        assert event is not None
        await refresh_event_announcement(bot, session, event)

    edited = fake_bot_api.edited_messages[-1]
    assert edited.reply_markup is None
    assert "🚫 <b>Мероприятие отменено</b>" in (edited.text or "")


async def test_refresh_member_announcements_edits_only_going_planned_events(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed_event(session_factory)

    async with session_factory() as session:
        project_id = ids["project_id"]
        # Ещё одно planned-мероприятие, где Миша НЕ идёт → трогать не нужно.
        skip_event = Event(
            project_id=project_id,
            description="Кино",
            starts_at=STARTS_AT,
            location="Кинотеатр",
            created_by=ids["anya_id"],
            announcement_message_id=600,
        )
        session.add(skip_event)
        await session.flush()
        session.add(
            EventRSVP(
                event_id=skip_event.id,
                user_id=ids["misha_id"],
                status=RSVPStatus.NOT_GOING,
                updated_by=ids["misha_id"],
            )
        )
        await session.commit()

    async with session_factory() as session:
        await refresh_member_announcements(
            bot, session, project_id=ids["project_id"], user_id=ids["misha_id"]
        )

    edited_ids = {m.message_id for m in fake_bot_api.edited_messages}
    assert edited_ids == {500}


async def test_refresh_member_announcements_skips_finalized_event(
    bot: Bot,
    fake_bot_api: FakeBotApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed_event(session_factory, finalized=True)

    async with session_factory() as session:
        await refresh_member_announcements(
            bot, session, project_id=ids["project_id"], user_id=ids["misha_id"]
        )

    assert fake_bot_api.edited_messages == []
