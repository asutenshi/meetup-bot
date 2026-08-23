import httpx

from meetup_bot.app import create_app
from meetup_bot.config import Settings


def _settings() -> Settings:
    return Settings(
        bot_token="123:abc",
        database_url="postgresql+asyncpg://user:pass@localhost/db",
    )


async def test_health() -> None:
    app = create_app(_settings())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_webhook_path_uses_bot_token() -> None:
    app = create_app(_settings())

    paths = {getattr(route, "path", None) for route in app.routes}

    assert "/webhook/123:abc" in paths
