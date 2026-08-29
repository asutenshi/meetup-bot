import datetime
import decimal

from meetup_bot.db.enums import RSVPStatus
from meetup_bot.db.models import Event, User
from meetup_bot.services.event_announcement import (
    build_announcement_text,
    build_rsvp_keyboard,
    rsvp_callback_data,
)

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


def test_rsvp_keyboard_callback_data() -> None:
    keyboard = build_rsvp_keyboard(42)
    datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]

    assert datas == [
        rsvp_callback_data(42, RSVPStatus.GOING),
        rsvp_callback_data(42, RSVPStatus.NOT_GOING),
    ]
    assert datas == ["rsvp:42:going", "rsvp:42:not_going"]
