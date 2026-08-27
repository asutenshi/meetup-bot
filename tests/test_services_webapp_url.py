from meetup_bot.services.webapp_url import build_web_app_url


def test_build_web_app_url_appends_app_path_and_project() -> None:
    url = build_web_app_url("https://example.com", project_payload="abc123")

    assert url == "https://example.com/app/?project=abc123"


def test_build_web_app_url_strips_trailing_slash_from_base() -> None:
    url = build_web_app_url("https://example.com/", project_payload="abc123")

    assert url == "https://example.com/app/?project=abc123"


def test_build_web_app_url_url_encodes_payload() -> None:
    url = build_web_app_url("https://example.com", project_payload="a b/c&d")

    assert url == "https://example.com/app/?project=a+b%2Fc%26d"
