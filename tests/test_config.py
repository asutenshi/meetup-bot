from meetup_bot.config import Settings


def test_settings_reads_required_fields() -> None:
    settings = Settings(
        bot_token="123:abc",
        database_url="postgresql+asyncpg://user:pass@localhost/db",
        public_base_url="https://example.com",
    )

    assert settings.bot_token == "123:abc"
    assert settings.database_url == "postgresql+asyncpg://user:pass@localhost/db"
    assert settings.public_base_url == "https://example.com"


def test_settings_defaults() -> None:
    settings = Settings(
        bot_token="123:abc",
        database_url="postgresql+asyncpg://user:pass@localhost/db",
    )

    assert settings.host == "0.0.0.0"
    assert settings.port == 8080
