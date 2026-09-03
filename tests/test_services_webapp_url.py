import pytest

from meetup_bot.services.webapp_url import (
    build_event_start_param,
    build_event_startapp_url,
    build_web_app_url,
    parse_event_start_param,
)


def test_build_web_app_url_appends_app_path_and_project() -> None:
    url = build_web_app_url("https://example.com", project_payload="abc123")

    assert url == "https://example.com/app/?project=abc123"


def test_build_web_app_url_strips_trailing_slash_from_base() -> None:
    url = build_web_app_url("https://example.com/", project_payload="abc123")

    assert url == "https://example.com/app/?project=abc123"


def test_build_web_app_url_url_encodes_payload() -> None:
    url = build_web_app_url("https://example.com", project_payload="a b/c&d")

    assert url == "https://example.com/app/?project=a+b%2Fc%26d"


def test_build_web_app_url_appends_event_id() -> None:
    url = build_web_app_url("https://example.com", project_payload="abc", event_id=42)

    assert url == "https://example.com/app/?project=abc&event=42"


def test_build_web_app_url_appends_attendance_event_id() -> None:
    url = build_web_app_url(
        "https://example.com", project_payload="abc", attendance_event_id=42
    )

    assert url == "https://example.com/app/?project=abc&attendance=42"


@pytest.mark.parametrize(
    "invite_payload",
    ["abc123", "xY_9-zZ", "trailing_", "_leading", "a_b_c"],
)
def test_event_start_param_round_trip(invite_payload: str) -> None:
    param = build_event_start_param(invite_payload=invite_payload, event_id=42)

    assert parse_event_start_param(param) == (invite_payload, 42)


@pytest.mark.parametrize(
    "param",
    ["", "noseparator", "abc_", "abc_notanumber", "_42", "abc_4_2x"],
)
def test_parse_event_start_param_rejects_bad_format(param: str) -> None:
    assert parse_event_start_param(param) is None


def test_build_event_startapp_url() -> None:
    url = build_event_startapp_url(
        bot_username="meetup_bot",
        short_name="app",
        invite_payload="xY_9-z",
        event_id=7,
    )

    assert url == "https://t.me/meetup_bot/app?startapp=xY_9-z_7"
