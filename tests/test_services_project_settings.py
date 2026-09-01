import pytest

from meetup_bot.db.models import ProjectSettings
from meetup_bot.services.project_settings import (
    SETTINGS_BY_ATTR,
    SettingValueError,
    apply_settings,
    parse_setting,
)


def test_parse_setting_accepts_valid_integer() -> None:
    assert parse_setting("reminder_send_hour", "7") == 7


@pytest.mark.parametrize(
    ("attr", "raw"),
    [
        ("reminder_days_threshold", "1"),
        ("reminder_days_threshold", "365"),
        ("missed_events_escalation_count", "1"),
        ("missed_events_escalation_count", "100"),
        ("reminder_send_hour", "0"),
        ("reminder_send_hour", "23"),
        ("all_command_throttle_seconds", "0"),
        ("all_command_throttle_seconds", "3600"),
    ],
)
def test_parse_setting_allows_range_bounds(attr: str, raw: str) -> None:
    assert parse_setting(attr, raw) == int(raw)


@pytest.mark.parametrize(
    ("attr", "raw"),
    [
        ("reminder_days_threshold", "0"),
        ("reminder_days_threshold", "366"),
        ("missed_events_escalation_count", "0"),
        ("reminder_send_hour", "24"),
        ("reminder_send_hour", "-1"),
        ("all_command_throttle_seconds", "3601"),
        ("reminder_send_hour", "не число"),
    ],
)
def test_parse_setting_rejects_out_of_range(attr: str, raw: str) -> None:
    with pytest.raises(SettingValueError) as exc:
        parse_setting(attr, raw)
    assert exc.value.code == "out_of_range"


def test_parse_setting_rejects_unknown_key() -> None:
    with pytest.raises(SettingValueError) as exc:
        parse_setting("nonsense", "5")
    assert exc.value.code == "unknown_key"


def test_parse_setting_accepts_valid_timezone() -> None:
    assert parse_setting("timezone", " Asia/Novosibirsk ") == "Asia/Novosibirsk"


def test_parse_setting_rejects_bad_timezone() -> None:
    with pytest.raises(SettingValueError) as exc:
        parse_setting("timezone", "Mars/Olympus")
    assert exc.value.code == "bad_timezone"
    assert "таймзону" in str(exc.value)


def test_all_command_throttle_seconds_is_editable() -> None:
    assert "all_command_throttle_seconds" in SETTINGS_BY_ATTR


def test_apply_settings_returns_only_changed_fields() -> None:
    settings = ProjectSettings(
        project_id=1,
        reminder_send_hour=20,
        reminder_days_threshold=14,
        timezone="Europe/Moscow",
    )
    changes = apply_settings(
        settings,
        {
            "reminder_send_hour": 9,
            "reminder_days_threshold": 14,
            "timezone": "Asia/Novosibirsk",
        },
    )

    assert settings.reminder_send_hour == 9
    assert settings.timezone == "Asia/Novosibirsk"
    changed_attrs = {attr for attr, _old, _new in changes}
    assert changed_attrs == {"reminder_send_hour", "timezone"}
    assert ("reminder_send_hour", 20, 9) in changes
